"""Unit tests for risk.py (multi-symbol aware)."""
import sys
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from risk import (position_size, round_qty, round_price,
                  size_for_min_notional, validate_size)


class TestRisk(unittest.TestCase):
    def test_position_size_btc_linear(self):
        # contractSize=1, distance 100, risk 1.5 -> 0.015 contracts
        s = position_size(100, 0, 1.5, contract_size=1.0)
        self.assertAlmostEqual(s, 0.015, places=4)

    def test_position_size_shib_huge(self):
        # contractSize=1000 (per 1000 SHIB), distance 0.0000005, risk 1.5
        s = position_size(0.00002, 0.0000175, 1.5, contract_size=1000.0)
        # 1.5 / (0.0000025 * 1000) = 600
        self.assertAlmostEqual(s, 600.0, delta=10)

    def test_position_size_zero(self):
        self.assertEqual(position_size(100, 100, 1.5), 0.0)

    def test_round_qty(self):
        self.assertAlmostEqual(round_qty(1.23456, 0.01), 1.23)
        self.assertAlmostEqual(round_qty(0.00123, 0.001), 0.001)

    def test_round_price(self):
        self.assertAlmostEqual(round_price(104.7382, 0.01), 104.73)
        self.assertAlmostEqual(round_price(0.000012345, 0.000001), 0.000012)

    def test_validate_size(self):
        ok, s = validate_size(0.0001, 0.001, 1.0)
        self.assertFalse(ok)
        ok, s = validate_size(0.5, 0.001, 1.0)
        self.assertTrue(ok)

    def test_min_notional_btc(self):
        # BTC @ 65000, min_amount 0.0001 -> notional 6.5 USD (>5 ok)
        q = size_for_min_notional(65000, 1.0, 0.0001, min_notional_usd=5.0)
        self.assertAlmostEqual(q, 0.0001, places=4)

    def test_min_notional_shib(self):
        # SHIB @ 0.00002, min_amount 10000 -> notional 0.20 USD (<5 bump)
        q = size_for_min_notional(0.00002, 1.0, 10000.0, min_notional_usd=5.0)
        self.assertGreater(q, 10000.0)


if __name__ == "__main__":
    unittest.main()
