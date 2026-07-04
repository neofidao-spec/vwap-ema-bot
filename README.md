# VWAP + EMA 9/21 Multi-Symbol Trend Bot (Bitget)

> **Strategy**: VWAP + EMA 9/21 + RSI 14 + Volume MA 20
> **Risk**: $1.5/trade/symbol, $0.5 on SHIB (overrides)
> **Leverage**: 15x (10x on SHIB/HYPE/DOGE)
> **Timeframe**: 5m
> **Symbols** (10 USDT‑Futures): BTC, ETH, SHIB, XRP, ADA, DOGE, TRX, SOL, LINK, HYPE

## 🎯 Strategy Logic (per spec)

### Trend Filter (BIAS)
- **long** only when `close > vwap` AND `ema9 > ema21`
- **short** only when `close < vwap` AND `ema9 < ema21`
- Counter‑bias setups are discarded.

### Entry A — Pullback Continuation
1. ≥ 6 candles respecting the trend (30 min @ 5m)
2. Pullback toward VWAP with **volume < MA20**
3. Rejection candle: lower wick ≥ 40 % of range, close in upper half (or mirror for shorts)
4. Previous candle confirms direction
5. **Limit** entry at close of confirmation candle
6. SL = `VWAP − 1.0 × ATR`

### Entry B — VWAP Breakout
1. Tight 3–6 candle consolidation (range ≤ 1.0 × ATR)
2. **Volume spike ≥ 1.5 × MA20** on the breakout candle
3. Close beyond `VWAP ± 0.5 × ATR`
4. **Market** entry
5. SL = `max(1.5 × ATR, swing‑low distance)`

### Stop / Take Profit
- **SL**: ATR‑based; anchored to VWAP for pullbacks, swing‑low/ATR for breakouts.
- **TP1** = `1.0 × ATR` → close **40 %**
- **TP2** = `2.0 × ATR` → close **60 %**
- **Trailing** after TP1: SL = `max(entry + 0.5 × ATR step, EMA9)`.
- **Invalidation**: VWAP crossed against the side with **vol > MA20** → market close.

> ⚠️ **Crucial safety:** SL & TP plan orders are sent to Bitget **only AFTER** the entry order is confirmed filled. No orphan SL/TP that could leak exposure.

## 🏗️ Architecture

```
config.yaml                       — 10 symbols, per-symbol overrides (SHIB risk, leverage)
src/
├── indicators.py                 — EMA / RSI / ATR / volume MA / intraday VWAP (pure numpy+pandas)
├── strategy.py                   — bias + pullback + breakout + invalidation
├── bitget_api.py                 — SharedBitget (1 ccxt) + BitgetClient per symbol
├── risk.py                       — position sizing, rounding, min-notional
├── engine_multi.py               — MultiSymbolEngine, per-symbol state machine
└── engine.py                     — legacy single-symbol version (kept for reference)
tests/
├── test_indicators.py            — 5 tests
├── test_strategy.py              — 3 tests
├── test_risk.py                  — 7 tests (BTC, SHIB scale, round, min-notional)
└── test_engine_multi.py          — 3 tests (init, tick, fake-candle scale)
```

## 🚀 Run

```bash
cd /root/trading-bot/vwap-bot

# 1. install deps
pip3 install -r requirements.txt

# 2. credentials (already in .env, chmod 600)
ls -la .env   # should be -rw------

# 3. dry-run validation: live Bitget, no real orders
python3 src/engine_multi.py --once

# 4. dry-run loop on a subset
python3 src/engine_multi.py --loop --loop-seconds 60 --symbols BTC/USDT:USDT,ETH/USDT:USDT

# 5. when ready for live:
#    - edit config.yaml: execution.dry_run: false
#    - deposit USDT to perps wallet
#    - start the loop
nohup python3 src/engine_multi.py --loop --loop-seconds 60 >> logs/runtime.log 2>&1 &
```

## 🧪 Tests

```bash
PYTHONPATH=src python3 -m unittest discover tests -v
# Expected: 19 tests, all OK
```

## ⚠️ Safety Checklist Before Live

- [ ] Funded USDT‑Futures wallet (~$30 recommended for safety)
- [ ] `dry_run: false` only after 24 h of clean dry‑run
- [ ] First week: cap risk_usd to **$0.5** per trade
- [ ] Monitor logs at `logs/vwap_bot.log` and Telegram notifications (if enabled)

## 📊 Risk Parameters

| Symbol | Default risk | Default leverage | Notes |
|--------|--------------|------------------|-------|
| BTC / ETH / SOL / LINK / XRP / ADA / TRX | $1.5 | 15x | per spec |
| SHIB | $0.5 | 10x | high volatility override |
| HYPE / DOGE | $1.5 | 10x | moderate volatility |

Override via `symbol_overrides:` block in `config.yaml`.

## 🔗 GitHub

<https://github.com/neofidao-spec/vwap-ema-bot>

## ⚠️ Disclaimer

Real money trading bot. Test thoroughly, start small, and never risk more than you can lose.
