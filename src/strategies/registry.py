"""Strategy registry loader and validator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "strategy_id",
    "name",
    "strategy_type",
    "status",
    "target_weight",
    "min_weight",
    "max_weight",
    "rebalance_frequency",
    "transaction_cost_bps_buy",
    "transaction_cost_bps_sell",
    "risk_limit_profile",
    "backtest_status",
    "walk_forward_status",
    "owner",
    "failure_modes",
}


@dataclass(frozen=True)
class StrategyRecord:
    strategy_id: str
    name: str
    strategy_type: str
    status: str
    target_weight: float
    min_weight: float
    max_weight: float
    raw: dict[str, Any]


def load_strategy_registry(path: str | Path) -> list[StrategyRecord]:
    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    rows = payload["strategies"] if isinstance(payload, dict) else payload
    records = []
    for index, row in enumerate(rows, start=1):
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ValueError(f"strategy row {index} missing fields: {sorted(missing)}")
        records.append(
            StrategyRecord(
                strategy_id=str(row["strategy_id"]),
                name=str(row["name"]),
                strategy_type=str(row["strategy_type"]),
                status=str(row["status"]),
                target_weight=float(row["target_weight"]),
                min_weight=float(row["min_weight"]),
                max_weight=float(row["max_weight"]),
                raw=dict(row),
            )
        )
    return records


def registry_weights(records: list[StrategyRecord]) -> dict[str, float]:
    return {record.strategy_id: record.target_weight for record in records}

