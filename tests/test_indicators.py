"""Unit tests for indicators.py."""
import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from indicators import ema, rsi, atr, volume_ma, vwap_intraday, add_all  # noqa


def make_df(n=200):
    rng = np.random.default_rng(42)
    close = np.cumsum(rng.normal(0, 1, n)) + 100
    high = close + rng.normal(2, 0.5, n)
    low = close - rng.normal(2, 0.5, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.uniform(50, 200, n)
    ts = (1700000000000 + np.arange(n) * 5 * 60 * 1000).astype(np.int64)
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high,
        "low": low, "close": close, "volume": volume,
    })


class TestIndicators(unittest.TestCase):
    def test_ema_shape_and_first_value(self):
        df = make_df()
        e = ema(df['close'], 9)
        self.assertEqual(len(e), len(df))
        self.assertAlmostEqual(e.iloc[-1], df['close'].iloc[-1], delta=10.0)

    def test_rsi_bounds(self):
        df = make_df()
        r = rsi(df['close'], 14)
        self.assertTrue(((r >= 0) & (r <= 100)).all())

    def test_atr_positive(self):
        df = make_df()
        a = atr(df, 14)
        self.assertTrue((a.dropna() >= 0).all())

    def test_volume_ma(self):
        df = make_df()
        m = volume_ma(df['volume'], 20)
        self.assertEqual(m.iloc[0], df['volume'].iloc[0])

    def test_add_all(self):
        df = make_df()
        out = add_all(df)
        for col in ('ema9', 'ema21', 'rsi', 'atr', 'vol_ma', 'vwap'):
            self.assertIn(col, out.columns)


if __name__ == "__main__":
    unittest.main()
