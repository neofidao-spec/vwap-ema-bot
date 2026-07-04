"""
engine_multi.py — multi-symbol VWAP + EMA 9/21 trend-continuation bot.

Each tracked symbol carries its own state machine:
  - IDLE -> find setup -> place entry limit -> wait for fill
  - FILLED -> attach SL/TP plan orders (only after confirmed fill)
  - OPEN  -> monitor invalidation + TP1 + trailing SL

A shared ticker fires once per 5m to fetch all symbol candles in parallel.
"""
import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from indicators import add_all  # noqa: E402
from strategy import (SIDE_LONG, SIDE_SHORT, SIDE_BUY, SIDE_SELL,
                      Setup, detect_bias, evaluate,
                      should_exit_invalid)  # noqa: E402
from risk import (position_size, round_qty, round_price,
                  size_for_min_notional, validate_size)  # noqa: E402


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


def make_fake_candles(symbol: str, n=200, base_price: Optional[float] = None):
    """Generate synthetic candles around a per-symbol base price."""
    if base_price is None:
        base_price = {"BTC/USDT:USDT": 65000, "ETH/USDT:USDT": 3500,
                      "SOL/USDT:USDT": 150, "LINK/USDT:USDT": 18,
                      "XRP/USDT:USDT": 0.55, "ADA/USDT:USDT": 0.40,
                      "DOGE/USDT:USDT": 0.12, "TRX/USDT:USDT": 0.13,
                      "SHIB/USDT:USDT": 0.000018, "HYPE/USDT:USDT": 30.0}.get(symbol, 100)
    out = []
    t = int(time.time() * 1000) - n * 5 * 60 * 1000
    p = base_price
    for _ in range(n):
        t += 5 * 60 * 1000
        # SHIB-like noise scales differently
        vol_pct = 0.001 if "SHIB" in symbol else 0.005
        p = max(1e-9, p * (1 + random.uniform(-vol_pct, vol_pct)))
        o = p * (1 + random.uniform(-vol_pct / 2, vol_pct / 2))
        c = p * (1 + random.uniform(-vol_pct / 2, vol_pct / 2))
        h = max(o, c) * (1 + abs(random.uniform(0, vol_pct)))
        l = min(o, c) * (1 - abs(random.uniform(0, vol_pct)))
        v = random.uniform(100, 500) * (1000 if "SHIB" in symbol else 1)
        out.append([t, o, h, l, c, v])
    return out


class SymbolState:
    """All per-symbol mutable state."""
    def __init__(self, symbol: str, client, cfg_strategy: dict,
                 risk_usd: float, leverage: int,
                 contract_size: float, min_amount: float,
                 price_precision: float):
        self.symbol = symbol
        self.client = client
        self.cfg_strategy = cfg_strategy
        self.risk_usd = risk_usd
        self.leverage = leverage
        self.contract_size = contract_size
        self.min_amount = min_amount
        self.price_precision = price_precision
        self.pending_entry: Optional[dict] = None
        self.open_position: Optional[dict] = None
        self.last_candle_close_ts: Optional[int] = None
        self.log = logging.getLogger(f"vwap-bot.{symbol}")

    # -------------------- entry --------------------
    def send_entry(self, setup: Setup, last):
        atr = last['atr']
        risk_usd = self.risk_usd
        raw = position_size(setup.entry_price, setup.sl_price,
                            risk_usd, contract_size=self.contract_size)
        qty = max(self.min_amount, round_qty(raw, self.min_amount))
        # ensure min notional $5
        qty = max(qty, size_for_min_notional(setup.entry_price,
                                             self.contract_size, self.min_amount, 5.0))

        # --- BALANCE CAP: margin must not exceed available equity ---
        try:
            avail = 0
            if self.client is not None:
                bal = self.client.fetch_balance()
                info = bal.get('info', {})
                if isinstance(info, list) and info:
                    avail = float(info[0].get('available') or 0)
            max_notional = avail * self.leverage
            max_qty = max_notional / setup.entry_price if setup.entry_price > 0 else 0
            if max_qty < self.min_amount:
                self.log.info(f"skip: available={avail:.2f} USDT too small "
                              f"(max_notional={max_notional:.2f})")
                return
            if qty > max_qty:
                old_qty = qty
                qty = round_qty(max_qty, self.min_amount)
                self.log.info(f"qty capped {old_qty}->{qty} "
                              f"(avail={avail:.2f} lev={self.leverage}x)")
        except Exception as e:
            self.log.debug(f"balance cap check failed: {e}")

        qty = round_qty(qty, self.min_amount)
        ok, qty = validate_size(qty, self.min_amount)
        if not ok or qty <= 0:
            self.log.info(f"qty too small ({qty}), skip")
            return

        side_order = side_to_order_side(setup.side)
        tp1 = setup.entry_price + self.cfg_strategy['tp1_atr_mult'] * atr if setup.side == SIDE_LONG \
              else setup.entry_price - self.cfg_strategy['tp1_atr_mult'] * atr
        tp2 = setup.entry_price + self.cfg_strategy['tp2_atr_mult'] * atr if setup.side == SIDE_LONG \
              else setup.entry_price - self.cfg_strategy['tp2_atr_mult'] * atr
        entry_px = round_price(setup.entry_price, self.price_precision)
        sl_px = round_price(setup.sl_price, self.price_precision)
        tp1_px = round_price(tp1, self.price_precision)
        tp2_px = round_price(tp2, self.price_precision)

        self.log.info(f"SETUP [{setup.entry_mode}] {setup.side.upper()} qty={qty} "
                      f"entry={entry_px} sl={sl_px} tp1={tp1_px} tp2={tp2_px}")

        if self.client is None or not hasattr(self.client, 'place_entry_limit'):
            # dry-run
            self.pending_entry = {"setup": setup, "order_id": "DRY",
                                  "qty": qty, "placed_at": time.time(),
                                  "tp1": tp1_px, "tp2": tp2_px,
                                  "fill_simulated": False}
            return

        try:
            order = self.client.place_entry_limit(
                side=side_order, price=entry_px, size=qty,
                client_id=f"vwap_{self.symbol.replace('/','')}_{int(time.time())}")
            self.pending_entry = {"setup": setup, "order_id": order['id'],
                                  "qty": qty, "placed_at": time.time(),
                                  "tp1": tp1_px, "tp2": tp2_px,
                                  "fill_simulated": False}
        except Exception as e:
            self.log.error(f"entry failed: {e}")

    # -------------------- pending entry --------------------
    def manage_pending(self, df):
        p = self.pending_entry
        if p is None:
            return
        age = time.time() - p['placed_at']
        timeout = 300
        if self.client is None or not hasattr(self.client, 'fetch_ohlcv'):
            if not p['fill_simulated']:
                p['fill_simulated'] = True
                self._on_entry_filled(p)
                self.pending_entry = None
                return
        else:
            try:
                o = self.client.shared.exchange.fetch_order(p['order_id'], self.symbol)
                if o and o.get('status') == 'closed':
                    self._on_entry_filled(p)
                    self.pending_entry = None
                    return
            except Exception as e:
                self.log.debug(f"fetch_order: {e}")
        if age > timeout:
            self.log.info(f"entry timeout after {age:.0f}s, cancelling")
            if self.client and hasattr(self.client, 'cancel_order'):
                self.client.cancel_order(p['order_id'])
            self.pending_entry = None

    def _on_entry_filled(self, p):
        setup: Setup = p['setup']
        sl = round_price(setup.sl_price, self.price_precision)
        tp2 = p['tp2']
        side_close = side_to_close_side(setup.side)
        if self.client is None or not hasattr(self.client, 'place_sl_tp_plan'):
            self.log.info(f"[DRY] FILLED. sl_plan={sl} tp_plan={tp2}")
        else:
            try:
                self.client.place_sl_tp_plan(
                    side_close=side_close, size=p['qty'],
                    sl_price=sl, tp_price=tp2)
            except Exception as e:
                self.log.error(f"SL/TP plan failed: {e}")
        self.open_position = {
            "side": setup.side, "qty": p['qty'],
            "entry": setup.entry_price, "sl": sl,
            "tp1": p['tp1'], "tp2": tp2,
            "tp1_hit": False, "entry_at": time.time(),
        }

    # -------------------- position management --------------------
    def manage_position(self, df):
        pos = self.open_position
        if pos is None:
            return
        last = df.iloc[-1]
        close = last['close']
        atr = last['atr']
        if should_exit_invalid(df, pos['side'], self.cfg_strategy):
            self.log.warning("INVALIDATION: VWAP crossed against, market close")
            if self.client and hasattr(self.client, 'close_position_market'):
                try:
                    self.client.close_position_market(
                        side_open=side_to_order_side(pos['side']),
                        size=pos['qty'])
                except Exception as e:
                    self.log.error(f"market close failed: {e}")
            self.open_position = None
            return

        if not pos['tp1_hit']:
            tp1_hit = (pos['side'] == SIDE_LONG and close >= pos['tp1']) or \
                      (pos['side'] == SIDE_SHORT and close <= pos['tp1'])
            if tp1_hit:
                pos['tp1_hit'] = True
                partial = pos['qty'] * self.cfg_strategy['tp1_size_pct']
                self.log.info(f"TP1 hit, close partial {partial:.4f}, trail rest")
                if self.client and hasattr(self.client, 'close_position_market'):
                    try:
                        self.client.close_position_market(
                            side_open=side_to_order_side(pos['side']),
                            size=partial)
                        pos['qty'] -= partial
                    except Exception as e:
                        self.log.error(f"partial close failed: {e}")
        else:
            trail_step = self.cfg_strategy['trail_atr_mult'] * atr
            if pos['side'] == SIDE_LONG:
                new_sl = max(pos['sl'], last['ema9'])
                new_sl = max(new_sl, pos['entry'] + trail_step)
                if new_sl > pos['sl']:
                    pos['sl'] = new_sl
                    self.log.info(f"TRAIL SL -> {new_sl:.6f}")
            elif pos['side'] == SIDE_SHORT:
                new_sl = min(pos['sl'], last['ema9'])
                new_sl = min(new_sl, pos['entry'] - trail_step)
                if new_sl < pos['sl']:
                    pos['sl'] = new_sl
                    self.log.info(f"TRAIL SL -> {new_sl:.6f}")


class MultiSymbolEngine:
    def __init__(self, cfg: dict, dry_run: bool):
        self.cfg = cfg
        self.dry_run = dry_run
        self.log = logging.getLogger("vwap-bot.engine")
        self.states: Dict[str, SymbolState] = {}
        self._setup_clients()

    def _setup_clients(self):
        symbols = self.cfg['symbols']
        overrides = self.cfg.get('symbol_overrides', {}) or {}

        if self.dry_run:
            self.log.info(f"DRY-RUN mode for {len(symbols)} symbols")
            shared = None
        else:
            load_dotenv()
            from bitget_api import SharedBitget, BitgetClient
            api_key = os.getenv(self.cfg['bitget']['api_key_env'])
            api_secret = os.getenv(self.cfg['bitget']['api_secret_env'])
            passphrase = os.getenv(self.cfg['bitget']['api_passphrase_env'])
            shared = SharedBitget(api_key, api_secret, passphrase,
                                  base_url=self.cfg['bitget']['base_url'])
            shared.load_markets()
            BitgetClient  # noqa

        for sym in symbols:
            sym_overrides = overrides.get(sym, {}) if isinstance(overrides, dict) else {}
            risk_usd = float(sym_overrides.get('risk_usd', self.cfg['risk_usd']))
            leverage = int(sym_overrides.get('leverage', self.cfg['leverage']))
            if self.dry_run:
                client = None
                contract_size = 1.0
                min_amount = 1.0
                price_prec = 0.0001 if "SHIB" in sym else 0.01
            else:
                bc = BitgetClient(shared, sym, leverage=leverage,
                                  margin_coin=self.cfg['margin_coin'],
                                  product_type=self.cfg['product_type'])
                client = bc
                contract_size = bc.contract_size
                min_amount = bc.min_amount
                price_prec = bc.price_precision
            self.states[sym] = SymbolState(
                symbol=sym, client=client,
                cfg_strategy=self.cfg['strategy'],
                risk_usd=risk_usd, leverage=leverage,
                contract_size=contract_size, min_amount=min_amount,
                price_precision=price_prec,
            )
            self.log.info(f"watching {sym} risk=${risk_usd} lev={leverage}x "
                          f"contractSize={contract_size} minAmount={min_amount}")

    # -------------------- main tick --------------------
    def tick(self):
        try:
            self._tick()
        except Exception as e:
            self.log.exception(f"engine tick failed: {e}")

    def _tick(self):
        open_count = sum(1 for s in self.states.values() if s.open_position is not None)
        cap = self.cfg.get('max_open_positions', 99)
        for sym, st in self.states.items():
            try:
                self._tick_symbol(st, open_count, cap)
            except Exception as e:
                st.log.exception(f"tick error: {e}")

    def _tick_symbol(self, st: SymbolState, open_count: int, cap: int):
        if st.client is None or not hasattr(st.client, 'fetch_ohlcv'):
            raw = make_fake_candles(st.symbol, n=self.cfg['lookback_bars'])
        else:
            raw = st.client.fetch_ohlcv(timeframe=self.cfg['timeframe'],
                                        limit=self.cfg['lookback_bars'])
        df = ohlcv_to_df(raw)
        if df.empty:
            return
        last_ts = int(df['timestamp'].iloc[-1])
        if last_ts == st.last_candle_close_ts:
            return
        st.last_candle_close_ts = last_ts

        df = add_all(df,
                     ema_fast=st.cfg_strategy['ema_fast'],
                     ema_slow=st.cfg_strategy['ema_slow'],
                     rsi_period=st.cfg_strategy['rsi_period'],
                     atr_period=14,
                     vol_period=st.cfg_strategy['volume_lookback'])
        last = df.iloc[-1]
        st.log.info(
            f"close={last['close']:.6f} vwap={last['vwap']:.6f} "
            f"rsi={last['rsi']:.1f} bias={detect_bias(last)} "
            f"pos={'yes' if st.open_position else 'no'} "
            f"pend={'yes' if st.pending_entry else 'no'}"
        )

        if st.open_position is not None:
            st.manage_position(df)
            return
        if st.pending_entry is not None:
            st.manage_pending(df)
            return
        # only consider new entries if global cap not reached
        if open_count >= cap:
            return
        setup = evaluate(df, st.cfg_strategy, prefer="pullback")
        if setup is None:
            return
        st.send_entry(setup, last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE.parent / "config.yaml"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop-seconds", type=int, default=60)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--symbols", help="comma-sep subset of symbols to watch", default=None)
    args = ap.parse_args()

    cfg = load_cfg(Path(args.config))
    if args.symbols:
        cfg['symbols'] = [s.strip() for s in args.symbols.split(",")]

    log_file = Path(cfg['scheduler']['log_file'])
    if not log_file.is_absolute():
        log_file = HERE.parent / log_file
    setup_logging(log_file)
    log = logging.getLogger("vwap-bot.main")
    log.info(f"Boot vwap-bot (multi) | dry_run={cfg['execution']['dry_run']} | "
             f"{len(cfg['symbols'])} symbols | risk=${cfg['risk_usd']}")

    engine = MultiSymbolEngine(cfg, dry_run=cfg['execution']['dry_run'])

    if args.once:
        engine.tick()
        return
    if args.loop:
        while True:
            engine.tick()
            time.sleep(args.loop_seconds)


if __name__ == "__main__":
    main()
