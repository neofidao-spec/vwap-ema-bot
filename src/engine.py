"""
engine.py — main loop.

Flow per tick:
  1. fetch OHLCV
  2. compute indicators
  3. if no position:    try to find setup -> place entry limit -> wait for fill
  4. if position open:
       - check invalidation (VWAP crossed with vol spike) -> market close
       - if entry limit not filled within 5 min: cancel
       - else once filled:  place SL and TP plan orders (SL/TP only after fill!)
       - monitor TP1 hit:   trail with EMA9 / ATR/2
"""
import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from indicators import add_all  # noqa: E402
from strategy import (SIDE_LONG, SIDE_SHORT, SIDE_BUY, SIDE_SELL,
                      Setup, detect_bias, evaluate,
                      should_exit_invalid)  # noqa: E402
from risk import position_size  # noqa: E402


def setup_logging(log_file: Path):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        handlers=[logging.FileHandler(log_file),
                  logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("vwap-bot")


def load_cfg(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def ohlcv_to_df(raw) -> pd.DataFrame:
    return pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])


def side_to_order_side(side: str) -> str:
    return SIDE_BUY if side == SIDE_LONG else SIDE_SELL


def side_to_close_side(side: str) -> str:
    return SIDE_SELL if side == SIDE_LONG else SIDE_BUY


def make_fake_candles(n=200, base_price=65000.0):
    out = []
    t = int(time.time() * 1000) - n * 5 * 60 * 1000
    p = base_price
    for _ in range(n):
        t += 5 * 60 * 1000
        p = max(1.0, p + random.uniform(-50, 50))
        o = p + random.uniform(-10, 10)
        c = p + random.uniform(-10, 10)
        h = max(o, c) + random.uniform(5, 25)
        l = min(o, c) - random.uniform(5, 25)
        v = random.uniform(100, 500)
        out.append([t, o, h, l, c, v])
    return out


class VwapBot:
    def __init__(self, cfg: dict, dry_run: bool, client=None):
        self.cfg = cfg
        self.dry_run = dry_run
        self.logger = logging.getLogger("vwap-bot.engine")

        if not dry_run and client is None:
            load_dotenv()
            from bitget_api import BitgetClient
            self.client = client or BitgetClient(
                api_key=os.getenv(cfg['bitget']['api_key_env']),
                api_secret=os.getenv(cfg['bitget']['api_secret_env']),
                passphrase=os.getenv(cfg['bitget']['api_passphrase_env']),
                symbol=cfg['symbol'],
                product_type=cfg['product_type'],
                margin_coin=cfg['margin_coin'],
                leverage=cfg['leverage'],
                base_url=cfg['bitget']['base_url'],
            )
        else:
            self.client = client

        self.pending_entry = None
        self.open_position = None
        self.last_candle_close_ts = None

    # -------------------- public --------------------
    def tick(self):
        try:
            self._tick()
        except Exception as e:
            self.logger.exception(f"tick failed: {e}")

    def _tick(self):
        if self.client is not None and hasattr(self.client, 'fetch_ohlcv'):
            raw = self.client.fetch_ohlcv(timeframe=self.cfg['timeframe'],
                                          limit=self.cfg['lookback_bars'])
        else:
            raw = make_fake_candles(n=self.cfg['lookback_bars'])

        df = ohlcv_to_df(raw)
        if df.empty:
            self.logger.warning("no candle data, skipping tick")
            return
        last_ts = int(df['timestamp'].iloc[-1])
        if last_ts == self.last_candle_close_ts:
            return
        self.last_candle_close_ts = last_ts
        df = add_all(df,
                     ema_fast=self.cfg['strategy']['ema_fast'],
                     ema_slow=self.cfg['strategy']['ema_slow'],
                     rsi_period=self.cfg['strategy']['rsi_period'],
                     atr_period=14,
                     vol_period=self.cfg['strategy']['volume_lookback'])
        last = df.iloc[-1]
        self.logger.info(
            f"close={last['close']:.2f} vwap={last['vwap']:.2f} "
            f"ema9={last['ema9']:.2f} ema21={last['ema21']:.2f} "
            f"rsi={last['rsi']:.1f} atr={last['atr']:.2f} "
            f"vol/spike={last['volume']/last['vol_ma']:.2f}x bias={detect_bias(last)}"
        )

        if self.open_position:
            self._manage_position(df)
            return

        if self.pending_entry:
            self._manage_pending_entry(df)
            return

        setup = evaluate(df, self.cfg['strategy'], prefer="pullback")
        if setup is None:
            return
        self.logger.info(f"SETUP candidate: {setup}")
        self._send_entry(setup, df)

    # -------------------- entry --------------------
    def _send_entry(self, setup: Setup, df: pd.DataFrame):
        last = df.iloc[-1]
        risk_usd = self.cfg['risk_usd']
        atr = last['atr']
        qty_raw = position_size(setup.entry_price, setup.sl_price, risk_usd)
        qty = max(0.001, round(qty_raw, 0.001))
        if qty <= 0:
            self.logger.info("qty too small, skip")
            return

        side_order = side_to_order_side(setup.side)
        tp1 = setup.entry_price + self.cfg['strategy']['tp1_atr_mult'] * atr if setup.side == SIDE_LONG \
              else setup.entry_price - self.cfg['strategy']['tp1_atr_mult'] * atr
        tp2 = setup.entry_price + self.cfg['strategy']['tp2_atr_mult'] * atr if setup.side == SIDE_LONG \
              else setup.entry_price - self.cfg['strategy']['tp2_atr_mult'] * atr

        if self.dry_run:
            self.logger.info(f"[DRY] ENTRY {side_order} {qty} @ {setup.entry_price:.2f} "
                             f"(sl={setup.sl_price:.2f} tp1={tp1:.2f} tp2={tp2:.2f})")
            self.pending_entry = {
                "setup": setup,
                "order_id": "DRY",
                "qty": qty,
                "placed_at": time.time(),
                "tp1": tp1,
                "tp2": tp2,
                "fill_simulated": False,
            }
            return

        try:
            order = self.client.place_entry_limit(
                side=side_order,
                price=setup.entry_price,
                size=qty,
                client_id=f"vwap_{int(time.time())}",
            )
            self.pending_entry = {
                "setup": setup,
                "order_id": order['id'],
                "qty": qty,
                "placed_at": time.time(),
                "tp1": tp1,
                "tp2": tp2,
                "fill_simulated": False,
            }
        except Exception as e:
            self.logger.error(f"entry placement failed: {e}")

    # -------------------- pending entry --------------------
    def _manage_pending_entry(self, df: pd.DataFrame):
        p = self.pending_entry
        timeout = self.cfg['execution']['entry_timeout_sec']
        age = time.time() - p['placed_at']
        if self.dry_run and not p['fill_simulated']:
            p['fill_simulated'] = True
            self._on_entry_filled(p)
            self.pending_entry = None
            return
        if not self.dry_run:
            try:
                o = self.client.exchange.fetch_order(p['order_id'],
                                                     self.client._symbol_ccxt())
                if o and o.get('status') == 'closed':
                    self._on_entry_filled(p)
                    self.pending_entry = None
                    return
            except Exception as e:
                self.logger.warning(f"fetch_order failed: {e}")
        if age > timeout:
            self.logger.info(f"ENTRY LIMIT timeout after {age:.0f}s, cancelling")
            if not self.dry_run:
                self.client.cancel_order(p['order_id'])
            self.pending_entry = None

    def _on_entry_filled(self, p: dict):
        setup: Setup = p['setup']
        sl = setup.sl_price
        tp2 = p['tp2']
        side_close = side_to_close_side(setup.side)
        if self.dry_run:
            self.logger.info(f"[DRY] ENTRY FILLED. SL plan @ {sl:.2f}, TP plan @ {tp2:.2f}")
        else:
            try:
                self.client.place_sl_tp_plan(
                    side_close=side_close,
                    size=p['qty'],
                    sl_price=sl,
                    tp_price=tp2,
                )
            except Exception as e:
                self.logger.error(f"SL/TP plan placement failed: {e}")

        self.open_position = {
            "side": setup.side,
            "qty": p['qty'],
            "entry": setup.entry_price,
            "sl": sl,
            "tp1": p['tp1'],
            "tp2": tp2,
            "tp1_hit": False,
            "entry_at": time.time(),
        }

    # -------------------- position management --------------------
    def _manage_position(self, df: pd.DataFrame):
        pos = self.open_position
        last = df.iloc[-1]
        close = last['close']
        atr = last['atr']

        if should_exit_invalid(df, pos['side'], self.cfg['strategy']):
            self.logger.warning("Invalidation: VWAP crossed against with vol spike -> market close")
            if not self.dry_run:
                self.client.close_position_market(
                    side_open=side_to_order_side(pos['side']),
                    size=pos['qty'],
                )
            self.open_position = None
            return

        if not pos['tp1_hit']:
            tp1_hit = (pos['side'] == SIDE_LONG and close >= pos['tp1']) or \
                      (pos['side'] == SIDE_SHORT and close <= pos['tp1'])
            if tp1_hit:
                pos['tp1_hit'] = True
                partial = pos['qty'] * self.cfg['strategy']['tp1_size_pct']
                self.logger.info(f"TP1 hit -> close partial {partial:.3f}, trail rest")
                if not self.dry_run:
                    try:
                        self.client.close_position_market(
                            side_open=side_to_order_side(pos['side']),
                            size=partial,
                        )
                        pos['qty'] -= partial
                    except Exception as e:
                        self.logger.error(f"partial close failed: {e}")
        else:
            trail_step = self.cfg['strategy']['trail_atr_mult'] * atr
            if pos['side'] == SIDE_LONG:
                new_sl = max(pos['sl'], last['ema9'])
                new_sl = max(new_sl, pos['entry'] + trail_step)
                if new_sl > pos['sl']:
                    pos['sl'] = new_sl
                    self.logger.info(f"TRAIL SL -> {new_sl:.2f}")
            elif pos['side'] == SIDE_SHORT:
                new_sl = min(pos['sl'], last['ema9'])
                new_sl = min(new_sl, pos['entry'] - trail_step)
                if new_sl < pos['sl']:
                    pos['sl'] = new_sl
                    self.logger.info(f"TRAIL SL -> {new_sl:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE.parent / "config.yaml"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop-seconds", type=int, default=60)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg(Path(args.config))
    log_file = Path(cfg['scheduler']['log_file'])
    if not log_file.is_absolute():
        log_file = HERE.parent / log_file
    setup_logging(log_file)
    log = logging.getLogger("vwap-bot.main")
    log.info(f"Boot vwap-bot | dry_run={cfg['execution']['dry_run']} | "
             f"symbol={cfg['symbol']} tf={cfg['timeframe']} risk=${cfg['risk_usd']}")

    bot = VwapBot(cfg, dry_run=cfg['execution']['dry_run'])

    if args.once:
        bot.tick()
        return
    if args.loop:
        while True:
            bot.tick()
            time.sleep(args.loop_seconds)


if __name__ == "__main__":
    main()
