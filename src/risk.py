"""
risk.py — position sizing using exchange contract metadata.
"""
from typing import Optional


def position_size(entry: float, stop: float, risk_usd: float,
                  contract_size: float = 1.0) -> float:
    """
    Number of *contracts* such that a stop at `stop` loses exactly `risk_usd`.

    Returns 0 if distance is zero or invalid.
    """
    if contract_size <= 0:
        contract_size = 1.0
    distance = abs(entry - stop)
    if distance <= 0:
        return 0.0
    raw = risk_usd / (distance * contract_size)
    return max(0.0, raw)


def size_for_min_notional(price: float, contract_size: float,
                          min_amount: float, min_notional_usd: float = 5.0) -> float:
    """
    Ensure size covers min_amount * contract_size and min notional $5.
    """
    if price <= 0:
        return min_amount
    if min_amount * price * contract_size < min_notional_usd:
        return min_amount * (min_notional_usd / max(min_amount * price * contract_size, 1e-9))
    return min_amount


def round_qty(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    return float(int(qty / step) * step)


def round_price(price: float, precision: float) -> float:
    if precision <= 0:
        return price
    # truncate (not Python banker's rounding) — keeps SL above exchange min ticks
    return float(int(price / precision) * precision)


def validate_size(size: float, min_amount: float, max_size: float = 1e6):
    if size < min_amount:
        return False, 0.0
    return True, min(size, max_size)
