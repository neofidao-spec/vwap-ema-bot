"""
risk.py — position sizing helpers.
Risk-based sizing: shares/contracts = risk_usd / |entry - SL|.
"""
from typing import Tuple


def position_size(entry: float, stop: float, risk_usd: float,
                  contract_size: float = 1.0) -> float:
    """
    Compute number of contracts/shares such that a stop at `stop` loses
    exactly `risk_usd` (linear, no leverage in math — leverage lives on
    the exchange and just changes margin requirement, not PnL per unit).

    `contract_size` is the multiplier per contract (e.g. 0.001 BTC for
    a micro-size pair).  Returned value is in contracts.
    """
    if contract_size <= 0:
        contract_size = 1.0
    distance = abs(entry - stop)
    if distance <= 0:
        return 0.0
    raw = risk_usd / (distance * contract_size)
    return max(0.0, raw)


def round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return (value // step) * step


def validate_size(size: float, min_size: float, max_size: float) -> Tuple[bool, float]:
    if size < min_size:
        return False, 0.0
    return True, min(size, max_size)
