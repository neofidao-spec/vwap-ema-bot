"""Unit tests for risk.py."""
import sys
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from risk import position_size, round_step, validate_size


class TestRisk(unittest.TestCase):
    def test_position_size_long(self):
        # risk $1.5, entry 100, sl 99 → distance = 1
        # size = 1.5 / 1 = 1.5 contracts
        self.assertAlmostEqual(position_size(100, 99, 1.5), 1.5)

    def test_position_size_zero_distance(self):
        self.assertEqual(position_size(100, 100, 1.5), 0.0)

    def test_position_size_negative_sl(self):
        # ensure no negative distance returns 0
        self.assertEqual(position_size(100, 50, 0.0), 0.0)

    def test_round_step(self):
        self.assertAlmostEqual(round_step(0.1234, 0.01), 0.12)
        self.assertAlmostEqual(round_step(0.00123, 0.001), 0.001)

    def test_validate_size(self):
        ok, s = validate_size(0.0001, 0.001, 1.0)
        self.assertFalse(ok)
        ok, s = validate_size(0.5, 0.001, 1.0)
        self.assertTrue(ok)
        self.assertAlmostEqual(s, 0.5)


if __name__ == "__main__":
    unittest.main()
