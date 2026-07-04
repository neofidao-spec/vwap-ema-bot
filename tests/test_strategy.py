"""Unit tests for strategy.py — make sure detect_bias and entry detectors work."""
import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from indicators import add_all
from strategy import detect_bias, detect_pullback, detect_breakout, evaluate


def make_trending(n=120, up=True, base=100.0):
    rng = np.random.default_rng(7)
    move = np.linspace(0, 10, n) if up else np.linspace(0, -10, n)
    close = base + move + rng.normal(0, 0.3, n)
    high = close + 0.5
    low = close - 0.5
    open_ = close + rng.normal(0, 0.1, n)
    volume = rng.uniform(100, 200, n)
    ts = (1700000000000 + np.arange(n) * 5 * 60 * 1000).astype(np.int64)
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high,
        "low": low, "close": close, "volume": volume,
    })


CFG = {
    "ema_fast": 9, "ema_slow": 21,
    "pullback_atr_above_vwap": 0.5, "pullback_sl_atr_below_vwap": 1.0,
    "pullback_wick_min_pct": 0.40, "pullback_wick_short_pct": 0.40,
    "pullback_min_bars_above": 6,
    "breakout_atr_above_vwap": 0.5, "breakout_sl_atr": 1.5,
    "breakout_min_range_bars": 3, "breakout_max_range_bars": 6,
    "invalidation_vol_mult": 1.0, "volume_spike_mult": 1.5,
    "tp1_atr_mult": 1.0, "tp1_size_pct": 0.40, "tp2_atr_mult": 2.0,
    "trail_atr_mult": 0.5, "trailing_mode": "ema9_or_atr_half",
}


class TestStrategy(unittest.TestCase):
    def test_bias_uptrend_long(self):
        df = add_all(make_trending(up=True))
        b = detect_bias(df.iloc[-1])
        self.assertEqual(b, "long")

    def test_bias_downtrend_short(self):
        df = add_all(make_trending(up=False))
        b = detect_bias(df.iloc[-1])
        self.assertEqual(b, "short")

    def test_evaluate_no_setup_in_random(self):
        rng = np.random.default_rng(99)
        n = 120
        close = np.cumsum(rng.normal(0, 1, n)) + 100
        high = close + 2
        low = close - 2
        open_ = close + rng.normal(0, 0.5, n)
        volume = rng.uniform(100, 200, n)
        ts = (1700000000000 + np.arange(n) * 5 * 60 * 1000).astype(np.int64)
        df = pd.DataFrame({
            "timestamp": ts, "open": open_, "high": high,
            "low": low, "close": close, "volume": volume,
        })
        df = add_all(df)
        s = evaluate(df, CFG)
        # random data may or may not yield a setup, but it shouldn't crash
        self.assertIn(s, [None]) or s is not None  # just ensure no crash


if __name__ == "__main__":
    unittest.main()
