# VWAP + EMA 9/21 Trend Continuation Bot (Bitget)

> Strategy: VWAP + EMA 9/21 + RSI 14 + volume MA 20
> Risk: $1.5 per trade, leverage 15x
> Timeframe: 5m

## 📊 Strategy Logic

### Trend Filter (BIAS)
- `long` only when **close > vwap** AND **ema9 > ema21**
- `short` only when **close < vwap** AND **ema9 < ema21**
- Otherwise: setup discarded (counter‑bias trades are skipped)

### Entry A — Pullback Continuation (default)
1. Price ≥ 30 min above VWAP, VWAP sloping up
2. Pullback approaches VWAP with **volume < vol_MA20**
3. Bullish rejection candle: **lower wick ≥ 40% of range, close in upper half**
4. Previous candle green (confirmation)
5. Entry: limit at close of confirmation candle
6. SL: `VWAP - 1.0 × ATR`

### Entry B — VWAP Breakout (momentum)
1. Consolidation 15–30 min around VWAP (range ≤ 1.0 × ATR)
2. **Volume spike ≥ 1.5 × vol_MA20** on the breakout candle
3. Close beyond `VWAP + 0.5 × ATR`
4. Entry: market
5. SL: below swing low **or** `1.5 × ATR`, whichever is farther

### Stop Loss
- Pullback: `VWAP - 1.0 × ATR`
- Breakout:  `min(swing_low, entry - 1.5 × ATR)`

### Take Profit
- **TP1**: `1.0 × ATR` from entry → close 40%
- **TP2**: `2.0 × ATR` from entry → close remaining
- After TP1: **trail** at max(`entry + 0.5×ATR step`, `EMA9`)

### Invalidation Exit
If VWAP crossed against our side with **volume > MA20**, exit market.

## 🚀 Run

```bash
# 1. install deps
pip3 install -r requirements.txt

# 2. configure credentials
cp .env.example .env
# edit .env with your Bitget API key/secret/passphrase

# 3. dry run (no real orders)
python3 src/engine.py --once
# or paper loop
python3 src/engine.py --loop --loop-seconds 30

# 4. live (edit config.yaml → execution.dry_run: false)
python3 src/engine.py --once
```

## 🧪 Tests

```bash
PYTHONPATH=src python3 -m unittest discover tests -v
```

## ⚠️ Disclaimer

This bot trades **real money** on Bitget USDT‑Futures. Always:
- Test with `dry_run: true` first.
- Verify on a **testnet** if you have one.
- Never risk more than you can afford to lose.
