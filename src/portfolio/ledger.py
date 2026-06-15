"""Portfolio ledger skeleton for strategy-level accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping


@dataclass(frozen=True)
class LedgerEntry:
    as_of_date: date
    strategy_id: str
    current_weight: float
    proposed_weight: float
    allocation_dollars: float
    daily_return: float = 0.0
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    turnover: float = 0.0
    transaction_cost: float = 0.0
    signal_status: str = "pending"
    risk_status: str = "pending"


def validate_weights(weights: Mapping[str, float], tolerance: float = 1e-8) -> bool:
    total = sum(float(value) for value in weights.values())
    if abs(total - 1.0) > tolerance:
        raise ValueError(f"portfolio weights must sum to 1.0, got {total:.10f}")
    if any(value < 0 for value in weights.values()):
        raise ValueError("portfolio weights must be non-negative")
    return True


def allocation_dollars(weights: Mapping[str, float], capital: float) -> dict[str, float]:
    validate_weights(weights)
    if capital < 0:
        raise ValueError("capital must be non-negative")
    return {strategy_id: weight * capital for strategy_id, weight in weights.items()}

