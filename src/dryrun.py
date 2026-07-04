"""Add a dummy fetch_ohlcv method for dry-run when no client is wired up."""
import random
import time


def attach_fake_candles(bot, n=200, base_price=65000.0):
    """Replace bot.client with a fake OHLCV generator."""
    state = {"t": int(time.time() * 1000) - n * 5 * 60 * 1000,
             "p": base_price, "n": n}

    def fake_fetch_ohlcv(timeframe="5m", limit=200):
        out = []
        for _ in range(limit):
            state["t"] += 5 * 60 * 1000
            drift = random.uniform(-50, 50)
            state["p"] = max(1.0, state["p"] + drift)
            o = state["p"] + random.uniform(-10, 10)
            c = state["p"] + random.uniform(-10, 10)
            h = max(o, c) + random.uniform(5, 25)
            l = min(o, c) - random.uniform(5, 25)
            v = random.uniform(100, 500)
            out.append([state["t"], o, h, l, c, v])
        return out

    bot.client = type("F", (), {})()
    bot.client.fetch_ohlcv = staticmethod(fake_fetch_ohlcv)
    bot.client.fetch_balance = staticmethod(lambda: {"USDT": {"free": 100.0}})
    bot.client.fetch_positions = staticmethod(lambda: [])
    bot.client.has_open_position = staticmethod(lambda: False)
    bot.client.place_entry_limit = staticmethod(
        lambda **kw: {"id": "FAKE", "status": "open"}
    )
    bot.client.place_entry_market = staticmethod(
        lambda **kw: {"id": "FAKE", "status": "closed"}
    )
    bot.client.place_sl_tp_plan = staticmethod(
        lambda **kw: {"id": "FAKE-SLTP", "status": "open"}
    )
    bot.client.cancel_order = staticmethod(lambda *a, **kw: True)
    bot.client.close_position_market = staticmethod(
        lambda **kw: {"id": "FAKE-CLOSE", "status": "closed"}
    )
    bot.client._symbol_ccxt = staticmethod(lambda: "BTC/USDT:USDT")
    return bot
