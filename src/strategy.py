"""
strategy.py — VWAP + EMA 9/21 trend continuation.

Two entry modes:
  A. PULLBACK continuation:   lower‑risk, tighter SL.
  B. BREAKOUT momentum:      wider SL, market entry.

Trend filter (BIAS):
  - long only when close > vwap AND ema9 > ema21
  - short only when close < vwap AND ema9 < ema21
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd


SIDE_LONG = "long"
SIDE_SHORT = "short"
SIDE_BUY = "buy"
SIDE_SELL = "sell"


@dataclass
class Setup:
    side: str           # "long" or "short"
    entry_mode: str     # "pullback" or "breakout"
    entry_price: float
    sl_price: float
    reason: str         # debug info


def detect_bias(last: pd.Series) -> str:
    """Return 'long', 'short' or 'none' based on trend filter."""
    if not (last['ema9'] > last['ema21']):
        if not (last['ema9'] < last['ema21']):
            return "none"
    if last['close'] > last['vwap'] and last['ema9'] > last['ema21']:
        return SIDE_LONG
    if last['close'] < last['vwap'] and last['ema9'] < last['ema21']:
        return SIDE_SHORT
    return "none"


def bars_above_vwap(df: pd.DataFrame, side: str) -> int:
    """Count consecutive candles respecting the trend filter."""
    count = 0
    for _, row in df[::-1].iterrows():
        if side == SIDE_LONG and row['close'] > row['vwap'] and row['ema9'] > row['ema21']:
            count += 1
        elif side == SIDE_SHORT and row['close'] < row['vwap'] and row['ema9'] < row['ema21']:
            count += 1
        else:
            break
    return count


def detect_pullback(df: pd.DataFrame, cfg: dict, bias: str) -> Optional[Setup]:
    """A. VWAP pullback continuation."""
    if bias == "none":
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if not cfg_valid(cfg):
        return None
    min_bars = cfg['pullback_min_bars_above']
    bars = bars_above_vwap(df.iloc[:-1], bias)
    if bars < min_bars:
        return None

    body = last['close'] - last['open']
    candle_range = last['high'] - last['low']
    if candle_range <= 0:
        return None

    atr = last['atr']
    vwap = last['vwap']

    # Long pullback
    if bias == SIDE_LONG:
        # pullback touched near vwap: low within 0.5*ATR of vwap
        if not (last['low'] <= vwap + 0.5 * atr):
            return None
        # volume down (last vol < vol_ma)
        if not (last['volume'] < last['vol_ma']):
            return None
        # candle close green (rejection candle is bullish)
        if not (body > 0):
            return None
        # body in upper half (real rejection has body in upper half; not strict close position)
        body_mid = (last['open'] + last['close']) / 2.0
        if not (body_mid >= last['low'] + 0.5 * candle_range):
            return None
        # lower wick >= 40% of range
        wick = min(last['open'], last['close']) - last['low']
        if (wick / candle_range) < cfg['pullback_wick_min_pct']:
            return None
        # entry: limit at close of last candle
        entry = last['close']
        # SL from ENTRY (not VWAP) — sweep winner: 30-40% better PF
        sl = entry - cfg['pullback_sl_atr_below_vwap'] * atr
        if sl >= entry:
            return None
        return Setup(SIDE_LONG, "pullback", entry, sl,
                     f"pullback long | wick%={wick/candle_range:.2f}")

    # Short pullback
    if bias == SIDE_SHORT:
        if not (last['high'] >= vwap - 0.5 * atr):
            return None
        if not (last['volume'] < last['vol_ma']):
            return None
        if not (body < 0):
            return None
        body_mid = (last['open'] + last['close']) / 2.0
        if not (body_mid <= last['high'] - 0.5 * candle_range):
            return None
        wick = last['high'] - max(last['open'], last['close'])
        if (wick / candle_range) < cfg['pullback_wick_short_pct']:
            return None
        entry = last['close']
        # SL from ENTRY (not VWAP) — sweep winner: 30-40% better PF
        sl = entry + cfg['pullback_sl_atr_below_vwap'] * atr
        if sl <= entry:
            return None
        return Setup(SIDE_SHORT, "pullback", entry, sl,
                     f"pullback short | wick%={wick/candle_range:.2f}")

    return None


def detect_breakout(df: pd.DataFrame, cfg: dict, bias: str) -> Optional[Setup]:
    """B. VWAP breakout momentum."""
    if bias == "none":
        return None
    last = df.iloc[-1]
    atr = last['atr']
    vwap = last['vwap']

    if not cfg_valid(cfg):
        return None

    window = df.iloc[-(cfg['breakout_max_range_bars']+1):-1]
    rng_high = window['high'].max()
    rng_low = window['low'].min()
    range_size = rng_high - rng_low

    # Consolidation: range tight (<= 1.0 * ATR)
    if range_size > 1.0 * atr:
        return None
    if len(window) < cfg['breakout_min_range_bars']:
        return None

    vol_spike = last['volume'] >= cfg['volume_spike_mult'] * last['vol_ma']
    if not vol_spike:
        return None

    if bias == SIDE_LONG and last['close'] >= vwap + cfg['breakout_atr_above_vwap'] * atr:
        entry = last['close']
        sl = min(rng_low, vwap - 0.3 * atr) - 0.5 * atr  # below swing low or 1.5 ATR
        sl = min(sl, entry - cfg['breakout_sl_atr'] * atr)
        if sl >= entry:
            return None
        return Setup(SIDE_LONG, "breakout", entry, sl,
                     f"breakout long | range={range_size:.2f} vol_spike={last['volume']/last['vol_ma']:.2f}x")

    if bias == SIDE_SHORT and last['close'] <= vwap - cfg['breakout_atr_above_vwap'] * atr:
        entry = last['close']
        sl = max(rng_high, vwap + 0.3 * atr) + 0.5 * atr
        sl = max(sl, entry + cfg['breakout_sl_atr'] * atr)
        if sl <= entry:
            return None
        return Setup(SIDE_SHORT, "breakout", entry, sl,
                     f"breakout short | range={range_size:.2f} vol_spike={last['volume']/last['vol_ma']:.2f}x")

    return None


def evaluate(df: pd.DataFrame, cfg: dict, prefer: str = "pullback") -> Optional[Setup]:
    """Main entry: choose a setup matching the bias."""
    bias = detect_bias(df.iloc[-1])
    if bias == "none":
        return None

    if prefer == "pullback":
        s = detect_pullback(df, cfg, bias)
        if s is not None:
            return s
        return detect_breakout(df, cfg, bias)
    else:
        s = detect_breakout(df, cfg, bias)
        if s is not None:
            return s
        return detect_pullback(df, cfg, bias)


def should_exit_invalid(df: pd.DataFrame, side: str, cfg: dict) -> bool:
    """Invalidation: VWAP crossed against side with volume > MA20."""
    if not cfg_valid(cfg):
        return False
    last = df.iloc[-1]
    vol_ok = last['volume'] > cfg['invalidation_vol_mult'] * last['vol_ma']
    if side == SIDE_LONG:
        return last['close'] < last['vwap'] and vol_ok
    if side == SIDE_SHORT:
        return last['close'] > last['vwap'] and vol_ok
    return False


def cfg_valid(cfg: dict) -> bool:
    return all(k in cfg for k in (
        "pullback_atr_above_vwap", "pullback_sl_atr_below_vwap",
        "pullback_wick_min_pct", "pullback_wick_short_pct",
        "pullback_min_bars_above",
        "breakout_atr_above_vwap", "breakout_sl_atr",
        "breakout_min_range_bars", "breakout_max_range_bars",
        "invalidation_vol_mult", "volume_spike_mult",
        "tp1_atr_mult", "tp1_size_pct", "tp2_atr_mult",
        "trail_atr_mult", "trailing_mode"))
