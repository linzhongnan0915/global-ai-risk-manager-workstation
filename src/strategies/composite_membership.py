"""Dynamic Combined Portfolio membership: equal-weight 1/N over eligible ACTIVE underlyings."""

from __future__ import annotations

import json
from pathlib import Path

from src.strategies.platform_registry import COMPOSITE_ID, RAPID_BACKTEST_IDS


def passes_composite_gate(summary: dict[str, object]) -> bool:
    """Research composite gate: valid run with positive net cumulative return and Sharpe."""
    return bool(summary.get("run_valid", False)) and float(summary.get("cumulative_net_return") or 0) > 0 and float(
        summary.get("net_sharpe") or 0
    ) > 0


def load_strategy_summary(factory_root: Path, strategy_id: str) -> dict[str, object]:
    return json.loads((factory_root / strategy_id / "summary.json").read_text(encoding="utf-8"))


def eligible_composite_constituent_ids(
    factory_root: Path,
    candidate_ids: tuple[str, ...] = RAPID_BACKTEST_IDS,
) -> tuple[str, ...]:
    """All underlying registry strategies that pass the composite gate (excludes Combined Portfolio)."""
    eligible: list[str] = []
    for strategy_id in candidate_ids:
        if strategy_id == COMPOSITE_ID:
            continue
        summary_path = factory_root / strategy_id / "summary.json"
        if not summary_path.exists():
            continue
        summary = load_strategy_summary(factory_root, strategy_id)
        if passes_composite_gate(summary):
            eligible.append(strategy_id)
    return tuple(sorted(eligible))


def composite_membership_for(strategy_id: str, eligible_ids: set[str]) -> str:
    return "ACTIVE" if strategy_id in eligible_ids else "REFERENCE_ONLY"


def equal_composite_weight(constituent_count: int) -> float:
    return 1.0 / constituent_count if constituent_count else 0.0


def composite_weights(constituent_ids: tuple[str, ...]) -> dict[str, float]:
    weight = equal_composite_weight(len(constituent_ids))
    return {strategy_id: weight for strategy_id in constituent_ids}
