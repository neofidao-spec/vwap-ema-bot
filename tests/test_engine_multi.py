"""Tests for multi-symbol engine."""
import sys
from pathlib import Path
import unittest

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from engine_multi import load_cfg, make_fake_candles, MultiSymbolEngine
from strategy import SIDE_LONG, SIDE_SHORT


CFG = {
    "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SHIB/USDT:USDT"],
    "margin_coin": "USDT",
    "product_type": "USDT-FUTURES",
    "timeframe": "5m",
    "lookback_bars": 200,
    "leverage": 15,
    "risk_usd": 1.5,
    "margin_mode": "isolated",
    "max_open_positions": 3,
    "strategy": {
        "ema_fast": 9, "ema_slow": 21, "rsi_period": 14,
        "rsi_long_min": 45, "rsi_long_max": 75,
        "rsi_short_min": 25, "rsi_short_max": 55,
        "volume_lookback": 20, "volume_spike_mult": 1.5,
        "pullback_atr_above_vwap": 0.5,
        "pullback_sl_atr_below_vwap": 1.0,
        "pullback_wick_min_pct": 0.40,
        "pullback_wick_short_pct": 0.40,
        "pullback_min_bars_above": 6,
        "breakout_atr_above_vwap": 0.5, "breakout_sl_atr": 1.5,
        "breakout_min_range_bars": 3, "breakout_max_range_bars": 6,
        "invalidation_vol_mult": 1.0,
        "tp1_atr_mult": 1.0, "tp1_size_pct": 0.40, "tp2_atr_mult": 2.0,
        "trail_atr_mult": 0.5, "trailing_mode": "ema9_or_atr_half",
    },
    "symbol_overrides": {
        "SHIB/USDT:USDT": {"risk_usd": 0.5, "leverage": 10},
    },
    "scheduler": {"enabled": True, "cron": "*/5 * * * *", "log_file": "logs/vwap_bot.log"},
    "execution": {"dry_run": True},
    "bitget": {"api_key_env": "BITGET_API_KEY", "api_secret_env": "BITGET_API_SECRET",
               "api_passphrase_env": "BITGET_PASSPHRASE",
               "base_url": "https://api.bitget.com"},
    "telegram": {"enabled": False},
}


class TestEngine(unittest.TestCase):
    def test_fake_candles_per_symbol_scale(self):
        # different symbols produce different scales
        btc = make_fake_candles("BTC/USDT:USDT", n=50)
        shib = make_fake_candles("SHIB/USDT:USDT", n=50)
        btc_close = sum(c[4] for c in btc) / len(btc)
        shib_close = sum(c[4] for c in shib) / len(shib)
        self.assertGreater(btc_close, shib_close * 1000)  # BTC ~100000x > SHIB

    def test_engine_init_dry_run(self):
        engine = MultiSymbolEngine(CFG, dry_run=True)
        self.assertEqual(len(engine.states), 3)
        self.assertIn("BTC/USDT:USDT", engine.states)
        self.assertIn("SHIB/USDT:USDT", engine.states)
        # SHIB has overridden risk
        shib = engine.states["SHIB/USDT:USDT"]
        self.assertEqual(shib.risk_usd, 0.5)
        self.assertEqual(shib.leverage, 10)

    def test_engine_tick_no_crash(self):
        engine = MultiSymbolEngine(CFG, dry_run=True)
        # run a single tick - synthetic data won't always trigger setups but must not error
        engine.tick()


if __name__ == "__main__":
    unittest.main()
