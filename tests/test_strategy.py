"""Unit tests for strategy.py — validate engineered setup PASSES (not silently rejected)."""
import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from indicators import add_all
from strategy import detect_bias, detect_pullback, evaluate, SIDE_LONG


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


def make_pullback_setup():
    """
    Build engineered pullback:
      - 50-bar uptrend above vwap (so vwap sits below current price)
      - last bar: rejection pullback that actually touches vwap
    """
    n = 60
    prices = np.linspace(100, 110, n)  # steady uptrend
    df = pd.DataFrame({
        "timestamp": (1700000000000 + np.arange(n)*300000).astype(np.int64),
        "open": prices + 0.05,
        "high": prices + 0.2,
        "low": prices - 0.2,
        "close": prices,
        "volume": np.ones(n)*100.0,
    })
    # First, add indicators to know where vwap actually sits
    df_ind = add_all(df)
    last_vwap = df_ind["vwap"].iloc[-1]
    # Now mutate last bar so the LOW touches vwap (= pullback)
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("close")] = last_vwap + 0.15  # close above vwap
    df2.iloc[-1, df2.columns.get_loc("open")] = last_vwap + 0.10
    df2.iloc[-1, df2.columns.get_loc("low")] = last_vwap - 0.30   # wick well below open (>= 40% of range)
    df2.iloc[-1, df2.columns.get_loc("high")] = last_vwap + 0.5
    df2.iloc[-1, df2.columns.get_loc("volume")] = 70
    return df2


class TestStrategy(unittest.TestCase):
    def test_bias_uptrend_long(self):
        df = add_all(make_trending(up=True))
        self.assertEqual(detect_bias(df.iloc[-1]), "long")

    def test_bias_downtrend_short(self):
        df = add_all(make_trending(up=False))
        self.assertEqual(detect_bias(df.iloc[-1]), "short")

    def test_evaluate_random_no_crash(self):
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
        self.assertIn(s, [None]) or s is not None

    def test_engineered_pullback_pass(self):
        """Engineered pullback setup MUST produce a Setup object (regression test for bug)."""
        df = make_pullback_setup()
        df2 = add_all(df)
        self.assertEqual(detect_bias(df2.iloc[-1]), SIDE_LONG)
        result = detect_pullback(df2, CFG, SIDE_LONG)
        self.assertIsNotNone(result,
                            "engineered pullback setup should NOT be silently rejected")
        self.assertEqual(result.side, SIDE_LONG)
        self.assertEqual(result.entry_mode, "pullback")

    def test_pullback_low_no_reject_when_tiny_wick(self):
        """Tiny lower wick (no real rejection) should NOT pass."""
        n = 60
        prices = np.linspace(100, 110, n)
        df = pd.DataFrame({
            "timestamp": (1700000000000 + np.arange(n)*300000).astype(np.int64),
            "open": prices + 0.05, "high": prices + 0.2,
            "low": prices - 0.2, "close": prices,
            "volume": np.ones(n)*100.0,
        })
        df_ind = add_all(df)
        last_vwap = df_ind["vwap"].iloc[-1]
        df.iloc[-1, df.columns.get_loc("close")] = last_vwap + 0.15
        df.iloc[-1, df.columns.get_loc("open")] = last_vwap + 0.10  # tiny wick
        df.iloc[-1, df.columns.get_loc("low")] = last_vwap + 0.08
        df.iloc[-1, df.columns.get_loc("high")] = last_vwap + 0.5
        df.iloc[-1, df.columns.get_loc("volume")] = 70
        df2 = add_all(df)
        result = detect_pullback(df2, CFG, SIDE_LONG)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
