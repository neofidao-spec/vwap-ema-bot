"""Regression test for balance-cap bug — qty must be capped to balance * leverage."""
import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from engine_multi import MultiSymbolEngine, SymbolState


class FakeBitgetClient:
    """Simulates the Bitget API surface our engine uses."""
    def __init__(self, available=10.0):
        self._avail = available
        self.orders_placed = []

    def fetch_balance(self):
        return {"info": [{"available": str(self._avail), "accountEquity": str(self._avail)}]}

    def fetch_ohlcv(self, timeframe="5m", limit=200):
        return []

    def place_entry_limit(self, side, price, size, client_id=""):
        self.orders_placed.append({"side": side, "price": price, "size": size})
        return {"id": "test-order-id"}

    def has_open_position(self):
        return False

    def fetch_positions(self):
        return []

    def get_open_position(self):
        return None

    def place_sl_tp_plan(self, side_close, size, sl_price, tp_price):
        return {}


class TestBalanceCap(unittest.TestCase):
    def test_qty_capped_to_balance_leverage(self):
        """When position_size gives qty exceeding balance*leverage,
        engine MUST cap to that max (instead of letting Bitget reject 40762)."""

        sym = "BTC/USDT:USDT"
        cfg = {
            "symbols": [sym],
            "lookback_bars": 120,
            "timeframe": "5m",
            "strategy": {
                "ema_fast": 9, "ema_slow": 21,
                "pullback_atr_above_vwap": 0.5, "pullback_sl_atr_below_vwap": 1.0,
                "pullback_wick_min_pct": 0.40, "pullback_wick_short_pct": 0.40,
                "pullback_min_bars_above": 6,
                "breakout_atr_above_vwap": 0.5, "breakout_sl_atr": 1.5,
                "breakout_min_range_bars": 3, "breakout_max_range_bars": 6,
                "invalidation_vol_mult": 1.0, "volume_spike_mult": 1.5,
                "tp1_atr_mult": 1.0, "tp1_size_pct": 0.40, "tp2_atr_mult": 2.0,
                "trail_atr_mult": 0.5, "trailing_mode": "ema9_or_atr_half",
            },
            "risk_usd": 1.5, "leverage": 15, "margin_mode": "cross",
            "max_open_positions": 3,
        }

        eng = MultiSymbolEngine(cfg, dry_run=True)
        st = eng.states[sym]

        # Inject fake client with $8 available balance (realistic)
        fake = FakeBitgetClient(available=8.0)
        st.client = fake
        st.contract_size = 1.0
        st.min_amount = 0.001
        st.price_precision = 0.01

        from strategy import Setup
        setup = Setup(
            side="long",
            entry_mode="pullback",
            entry_price=0.32592,
            sl_price=0.32452,
            reason="test"
        )

        last = pd.Series({
            "atr": 0.0005,
            "vwap": 0.325,
            "ema9": 0.326, "ema21": 0.324,
            "close": 0.326, "high": 0.327, "low": 0.324, "open": 0.325,
        })

        st.send_entry(setup, last)

        self.assertTrue(fake.orders_placed,
                        "order should have been placed (not rejected by 40762)")
        placed = fake.orders_placed[-1]
        size = placed["size"]
        margin = size * 0.32592 / 15
        self.assertLessEqual(margin, 8.10,
                             f"margin ${margin:.2f} > balance $8.00 (would trigger 40762)")
        self.assertGreater(size, 0)
        self.assertLess(placed["price"], 0.33)
        print(f"\n  PASS: qty={size:.4f}, margin=${margin:.2f} ≤ $8.00 ✓")


if __name__ == "__main__":
    unittest.main()
