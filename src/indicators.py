"""
indicators.py — pure-numpy/pandas technical indicators
EMA, RSI, ATR, volume MA, and intraday VWAP.

Input DataFrame columns:
    ['timestamp', 'open', 'high', 'low', 'close', 'volume']
"""
import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average (standard EMA)."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI implementation."""
    delta = close.diff()
    gain = pd.Series(np.where(delta > 0, delta, 0.0), index=close.index)
    loss = pd.Series(np.where(delta < 0, -delta, 0.0), index=close.index)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder smoothing."""
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low,
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(window=period, min_periods=1).mean()


def vwap_intraday(df: pd.DataFrame) -> pd.Series:
    """Rolling VWAP that resets at each UTC day boundary."""
    tp = (df['high'] + df['low'] + df['close']) / 3.0
    pv = tp * df['volume']
    ts = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    date = ts.dt.date
    cum_pv = pv.groupby(date).cumsum()
    cum_vol = df['volume'].groupby(date).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap.ffill()


def add_all(df: pd.DataFrame,
            ema_fast: int = 9,
            ema_slow: int = 21,
            rsi_period: int = 14,
            atr_period: int = 14,
            vol_period: int = 20) -> pd.DataFrame:
    """Add every indicator the strategy needs in one call."""
    out = df.copy()
    out['ema9'] = ema(out['close'], ema_fast)
    out['ema21'] = ema(out['close'], ema_slow)
    out['rsi'] = rsi(out['close'], rsi_period)
    out['atr'] = atr(out, atr_period)
    out['vol_ma'] = volume_ma(out['volume'], vol_period)
    out['vwap'] = vwap_intraday(out)
    return out
