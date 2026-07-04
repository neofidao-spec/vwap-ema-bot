"""
bitget_api.py — thin wrapper around ccxt for Bitget USDT-Futures.

Endpoints we touch:
  * fetch OHLCV
  * set leverage + margin mode
  * place entry order (limit or market)
  * cancel order
  * place SL / TP as plan orders (trigger orders)
  * fetch open positions
  * close position (market)

Only v2 endpoints and HMAC-SHA256 signing (ccxt handles it).
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

import ccxt

log = logging.getLogger("vwap-bot.bitget")


class BitgetClient:
    def __init__(self, api_key: str, api_secret: str, passphrase: str,
                 symbol: str = "BTCUSDT", product_type: str = "USDT-FUTURES",
                 margin_coin: str = "USDT", leverage: int = 15,
                 base_url: str = "https://api.bitget.com"):
        self.symbol = symbol
        self.product_type = product_type
        self.margin_coin = margin_coin
        self.leverage = leverage

        self.exchange = ccxt.bitget({
            "apiKey": api_key,
            "secret": api_secret,
            "password": passphrase,
            "options": {
                "defaultType": "swap",
                "sandboxMode": False,
            },
            "urls": {"api": {"rest": base_url}},
        })

        # Initial account setup
        try:
            self._set_leverage(leverage)
        except Exception as e:
            log.warning(f"could not set leverage (maybe already set): {e}")

    def _symbol_ccxt(self) -> str:
        # ccxt uses "BTC/USDT:USDT" for linear futures
        if "/" not in self.symbol:
            base, quote = self.symbol[:-4], self.symbol[-4:]
            return f"{base}/{quote}:{quote}"
        return self.symbol

    def _set_leverage(self, lev: int):
        try:
            self.exchange.set_leverage(lev, self._symbol_ccxt(),
                                       params={"marginCoin": self.margin_coin,
                                               "productType": self.product_type,
                                               "marginMode": "isolated"})
        except Exception as e:
            log.debug(f"set_leverage fallback: {e}")
            # try alternate signature
            try:
                self.exchange.set_leverage(lev, self._symbol_ccxt())
            except Exception as e2:
                log.warning(f"set_leverage finally failed: {e2}")

    def fetch_ohlcv(self, timeframe: str = "5m", limit: int = 200) -> List[List]:
        """Returns list [ts, open, high, low, close, volume]."""
        return self.exchange.fetch_ohlcv(self._symbol_ccxt(), timeframe=timeframe, limit=limit)

    def fetch_balance(self) -> Dict[str, Any]:
        return self.exchange.fetch_balance({"productType": self.product_type,
                                            "marginCoin": self.margin_coin})

    def fetch_positions(self) -> List[Dict]:
        return self.exchange.fetch_positions([self._symbol_ccxt()],
                                             params={"productType": self.product_type,
                                                     "marginCoin": self.margin_coin})

    def has_open_position(self) -> bool:
        for p in self.fetch_positions():
            amt = float(p.get('contracts') or 0)
            if amt > 0:
                return True
        return False

    def place_entry_limit(self, side: str, price: float, size: float,
                          client_id: str = "") -> Dict:
        order = self.exchange.create_order(
            self._symbol_ccxt(),
            "limit",
            side,
            size,
            price,
            params={
                "marginCoin": self.margin_coin,
                "productType": self.product_type,
                "marginMode": "isolated",
                "clientOid": client_id or f"vwap_{int(time.time()*1000)}",
                "timeInForceValue": "GTC",
            },
        )
        log.info(f"ENTRY LIMIT placed: {side} {size} @ {price} → id={order.get('id')}")
        return order

    def place_entry_market(self, side: str, size: float, client_id: str = "") -> Dict:
        order = self.exchange.create_order(
            self._symbol_ccxt(),
            "market",
            side,
            size,
            None,
            params={
                "marginCoin": self.margin_coin,
                "productType": self.product_type,
                "marginMode": "isolated",
                "clientOid": client_id or f"vwap_{int(time.time()*1000)}",
            },
        )
        log.info(f"ENTRY MARKET placed: {side} {size} → id={order.get('id')}")
        return order

    def place_sl_tp_plan(self, side_close: str, size: float,
                         sl_price: float, tp_price: float) -> Dict:
        """
        Bitget plan orders (algo order) attach SL & TP to a position.
        side_close: 'sell' for closing long, 'buy' for closing short.
        """
        params = {
            "marginCoin": self.margin_coin,
            "productType": self.product_type,
            "marginMode": "isolated",
            "stopLoss": {"triggerPrice": sl_price, "holdSide": side_close},
            "takeProfit": {"triggerPrice": tp_price, "holdSide": side_close},
        }
        order = self.exchange.create_order(
            self._symbol_ccxt(),
            "market",
            side_close,
            size,
            None,
            params=params,
        )
        log.info(f"SL/TP plan placed: sl={sl_price} tp={tp_price}")
        return order

    def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        try:
            self.exchange.cancel_order(order_id, self._symbol_ccxt())
            return True
        except Exception as e:
            log.warning(f"cancel failed: {e}")
            return False

    def close_position_market(self, side_open: str, size: float) -> Dict:
        side_close = "sell" if side_open == "buy" else "buy"
        order = self.exchange.create_order(
            self._symbol_ccxt(),
            "market",
            side_close,
            size,
            None,
            params={
                "marginCoin": self.margin_coin,
                "productType": self.product_type,
                "marginMode": "isolated",
                "reduceOnly": True,
            },
        )
        log.info(f"POSITION CLOSED market: {side_close} {size}")
        return order
