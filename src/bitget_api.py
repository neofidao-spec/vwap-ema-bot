"""
bitget_api.py — ccxt wrapper per symbol.

Each BitgetClient encapsulates a single underlying ccxt.bitget instance
with a target symbol set on it. We use a SHARED ccxt client internally
so that load_markets() is called once and orders are routed by symbol.
"""
import logging
import time
from typing import Any, Dict, List, Optional

import ccxt

log = logging.getLogger("vwap-bot.bitget")


class SharedBitget:
    """One ccxt.bitget connection shared across symbols."""

    def __init__(self, api_key: str, api_secret: str, passphrase: str,
                 base_url: str = "https://api.bitget.com"):
        self.exchange = ccxt.bitget({
            "apiKey": api_key,
            "secret": api_secret,
            "password": passphrase,
            "options": {"defaultType": "swap", "sandboxMode": False},
            "urls": {"api": {"rest": base_url}},
        })
        self.markets = {}
        self._markets_loaded = False

    def load_markets(self):
        if not self._markets_loaded:
            self.markets = self.exchange.load_markets()
            self._markets_loaded = True
        return self.markets

    def set_leverage(self, symbol: str, leverage: int,
                     margin_coin: str = "USDT",
                     product_type: str = "USDT-FUTURES"):
        try:
            self.exchange.set_leverage(leverage, symbol,
                                       params={"marginCoin": margin_coin,
                                               "productType": product_type,
                                               "marginMode": "isolated"})
            return True
        except Exception as e:
            log.debug(f"set_leverage fallback for {symbol}: {e}")
            return False


class BitgetClient:
    """Per-symbol view over a SharedBitget."""

    def __init__(self, shared: SharedBitget, symbol: str,
                 leverage: int, margin_coin: str = "USDT",
                 product_type: str = "USDT-FUTURES"):
        self.shared = shared
        self.symbol = symbol
        self.leverage = leverage
        self.margin_coin = margin_coin
        self.product_type = product_type

        self.shared.load_markets()
        self.market_info = self.shared.markets.get(symbol, {})
        self.contract_size = float(self.market_info.get('contractSize') or 1.0)
        prec = (self.market_info.get('precision') or {})
        self.price_precision = float(prec.get('price') or 0.01)
        amt = self.market_info.get('limits', {}).get('amount', {})
        self.min_amount = float(amt.get('min') or 0.0)

        self.shared.set_leverage(symbol, leverage, margin_coin, product_type)

    # convenience pass-throughs
    def _ex(self):
        return self.shared.exchange

    def fetch_ohlcv(self, timeframe: str = "5m", limit: int = 200) -> List[List]:
        return self._ex().fetch_ohlcv(self.symbol, timeframe=timeframe, limit=limit)

    def fetch_balance(self) -> Dict[str, Any]:
        return self._ex().fetch_balance({"productType": self.product_type,
                                         "marginCoin": self.margin_coin})

    def fetch_positions(self) -> List[Dict]:
        try:
            return self._ex().fetch_positions([self.symbol],
                                              params={"productType": self.product_type,
                                                      "marginCoin": self.margin_coin})
        except Exception as e:
            log.debug(f"fetch_positions({self.symbol}) err: {e}")
            return []

    def has_open_position(self) -> bool:
        for p in self.fetch_positions():
            amt = abs(float(p.get('contracts') or 0))
            if amt > 0:
                return True
        return False

    def get_open_position(self) -> Optional[Dict]:
        for p in self.fetch_positions():
            amt = float(p.get('contracts') or 0)
            if abs(amt) > 0:
                return {
                    'side': 'long' if amt > 0 else 'short',
                    'qty': abs(amt),
                    'entry': float(p.get('entryPrice') or 0),
                    'unrealizedPL': float(p.get('unrealizedPnl') or 0),
                    'raw': p,
                }
        return None

    def place_entry_limit(self, side: str, price: float, size: float,
                          client_id: str = "") -> Dict:
        order = self._ex().create_order(
            self.symbol, "limit", side, size, price,
            params={"marginCoin": self.margin_coin,
                    "productType": self.product_type,
                    "marginMode": "isolated",
                    "clientOid": client_id or f"vwap_{int(time.time()*1000)}",
                    "timeInForceValue": "GTC"})
        log.info(f"[{self.symbol}] ENTRY LIMIT {side} {size} @ {price} -> {order.get('id')}")
        return order

    def place_sl_tp_plan(self, side_close: str, size: float,
                         sl_price: float, tp_price: float) -> Dict:
        params = {
            "marginCoin": self.margin_coin,
            "productType": self.product_type,
            "marginMode": "isolated",
            "stopLoss": {"triggerPrice": sl_price, "holdSide": side_close},
            "takeProfit": {"triggerPrice": tp_price, "holdSide": side_close},
        }
        order = self._ex().create_order(
            self.symbol, "market", side_close, size, None, params=params)
        log.info(f"[{self.symbol}] SL/TP plan: sl={sl_price} tp={tp_price}")
        return order

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._ex().cancel_order(order_id, self.symbol)
            return True
        except Exception as e:
            log.warning(f"cancel failed for {order_id}: {e}")
            return False

    def close_position_market(self, side_open: str, size: float) -> Dict:
        side_close = "sell" if side_open == "buy" else "buy"
        order = self._ex().create_order(
            self.symbol, "market", side_close, size, None,
            params={"marginCoin": self.margin_coin,
                    "productType": self.product_type,
                    "marginMode": "isolated",
                    "reduceOnly": True})
        log.info(f"[{self.symbol}] CLOSE market {side_close} {size}")
        return order
