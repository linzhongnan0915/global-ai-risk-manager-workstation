"""Research strategy catalog loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_CANDIDATE_FIELDS = {
    "strategy_id",
    "name",
    "current_status",
    "etf_universe",
    "signal",
    "rebalance",
    "data_readiness",
    "missing_data",
    "risk_manager_use",
}


def load_research_catalog(path: str | Path = "data/config/strategy_research_catalog.json") -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        payload = json.load(file)
    validate_research_catalog(payload)
    return payload


def flatten_strategy_candidates(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for family in catalog.get("strategy_families", []):
        for candidate in family.get("candidate_strategies", []):
            row = dict(candidate)
            row["family_id"] = family["family_id"]
            row["family_name"] = family["name"]
            row["source"] = family["source"]
            row["institutional_role"] = family["institutional_role"]
            candidates.append(row)
    return candidates


def validate_research_catalog(catalog: dict[str, Any], min_count: int = 20) -> None:
    families = catalog.get("strategy_families", [])
    if not families:
        raise ValueError("strategy research catalog must include strategy_families")
    candidates = flatten_strategy_candidates(catalog)
    if len(candidates) < min_count:
        raise ValueError(f"strategy research catalog must include at least {min_count} candidates")
    seen = set()
    for index, candidate in enumerate(candidates, start=1):
        missing = REQUIRED_CANDIDATE_FIELDS - set(candidate)
        if missing:
            raise ValueError(f"candidate {index} missing fields: {sorted(missing)}")
        strategy_id = candidate["strategy_id"]
        if strategy_id in seen:
            raise ValueError(f"duplicate strategy_id in research catalog: {strategy_id}")
        seen.add(strategy_id)
        if not candidate["etf_universe"]:
            raise ValueError(f"{strategy_id} must include at least one ETF or proxy")

