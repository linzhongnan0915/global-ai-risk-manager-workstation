"""Conservative allocation optimizer skeleton."""

from __future__ import annotations

from dataclasses import dataclass

from src.portfolio.ledger import validate_weights
from src.risk.transaction_cost import TransactionCostModel


@dataclass(frozen=True)
class AllocationRecommendation:
    current_weights: dict[str, float]
    proposed_weights: dict[str, float]
    estimated_transaction_cost: float
    approval_required: bool
    rationale: str


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weight total must be positive")
    normalized = {key: value / total for key, value in weights.items()}
    validate_weights(normalized, tolerance=1e-6)
    return normalized


def propose_allocation(
    current_weights: dict[str, float],
    strategy_scores: dict[str, float],
    min_weights: dict[str, float],
    max_weights: dict[str, float],
    capital: float,
    max_turnover: float = 0.15,
    cost_model: TransactionCostModel | None = None,
) -> AllocationRecommendation:
    """Blend current allocation with bounded score tilts.

    This deliberately avoids blind Sharpe maximization. The skeleton applies
    small tilts based on strategy score, caps weights, respects turnover, and
    always requires human approval for real allocation changes.
    """

    validate_weights(current_weights, tolerance=1e-6)
    model = cost_model or TransactionCostModel()
    score_sum = sum(max(score, 0.0) for score in strategy_scores.values())
    if score_sum == 0:
        raw_target = dict(current_weights)
    else:
        raw_target = {
            strategy_id: max(strategy_scores.get(strategy_id, 0.0), 0.0) / score_sum
            for strategy_id in current_weights
        }
    bounded = {}
    for strategy_id, weight in raw_target.items():
        floor = min_weights.get(strategy_id, 0.0)
        cap = max_weights.get(strategy_id, 1.0)
        bounded[strategy_id] = min(max(weight, floor), cap)
    target = normalize_weights(bounded)

    turnover = sum(abs(target[key] - current_weights.get(key, 0.0)) for key in target)
    if turnover > max_turnover:
        shrink = max_turnover / turnover
        target = normalize_weights(
            {
                key: current_weights[key] + (target[key] - current_weights[key]) * shrink
                for key in current_weights
            }
        )

    cost = model.rebalance_cost(current_weights, target, capital)
    return AllocationRecommendation(
        current_weights=dict(current_weights),
        proposed_weights=target,
        estimated_transaction_cost=cost,
        approval_required=True,
        rationale=(
            "Score-tilted proposal constrained by min/max weights, turnover, "
            "transaction cost, diversification, and mandatory human approval."
        ),
    )

