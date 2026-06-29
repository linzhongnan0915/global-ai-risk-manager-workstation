"""Paper allocation workbench report artifacts.

These reports persist an operator's paper allocation draft for review. They do
not approve, apply, trade, or mutate NAV/P&L.
"""

from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = "paper_allocation_workbench_report_v1"
TOLERANCE = 0.000001


def _reports_dir(root: Path) -> Path:
    return root / "data" / "automation" / "allocation_reports"


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _row(row: dict[str, Any]) -> dict[str, Any]:
    uid = str(row.get("strategy_uid") or "").strip()
    if not uid:
        raise ValueError("allocation report row missing strategy_uid")
    current = _safe_float(row.get("current_weight"))
    suggested = _safe_float(row.get("suggested_weight", row.get("recommended_weight")))
    target = _safe_float(row.get("target_weight", row.get("proposed_weight")))
    if current is None or target is None:
        raise ValueError(f"allocation report row missing numeric current/target weight for {uid}")
    delta = target - current
    action = str(row.get("action") or row.get("suggested_action") or row.get("action_status") or "").upper()
    if not action:
        if delta > TOLERANCE:
            action = "INCREASE"
        elif delta < -TOLERANCE:
            action = "REDUCE"
        else:
            action = "HOLD"
    return {
        "strategy_uid": uid,
        "display_name": row.get("display_name") or row.get("strategy_name") or uid,
        "current_weight": current,
        "suggested_weight": suggested,
        "target_weight": target,
        "delta": delta,
        "score": _safe_float(row.get("score")),
        "action": action,
        "reason": row.get("reason") or row.get("recommendation_reason") or "Operator paper allocation draft row.",
        "evidence_status": row.get("evidence_status"),
        "ml_status": row.get("ml_status"),
        "source_artifacts": row.get("source_artifacts") or [],
    }


def write_paper_allocation_report(
    root: str | Path,
    rows: list[dict[str, Any]],
    *,
    source_proposal_artifact: str | None = None,
    draft_summary: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("allocation report rows must be a non-empty list")

    root_path = Path(root)
    generated_at = _now(now)
    normalized = [_row(row) for row in rows]
    target_sum = sum(float(row["target_weight"]) for row in normalized)
    action_counts: dict[str, int] = {}
    for row in normalized:
        action_counts[row["action"]] = action_counts.get(row["action"], 0) + 1
    payload = {
        "ok": True,
        "source": SOURCE,
        "generated_at": generated_at.isoformat(),
        "as_of_date": generated_at.date().isoformat(),
        "source_proposal_artifact": source_proposal_artifact,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "nav_pnl_mutation": False,
        "approved_plan_created": False,
        "paper_apply_created": False,
        "live_trading": False,
        "brokerage_execution": False,
        "review_only": True,
        "target_weight_sum": target_sum,
        "weight_sum_target": 1.0,
        "weight_sum_tolerance": TOLERANCE,
        "sums_to_100pct": abs(target_sum - 1.0) <= TOLERANCE,
        "residual_weight": 1.0 - target_sum,
        "row_count": len(normalized),
        "action_counts": action_counts,
        "draft_summary": deepcopy(draft_summary or {}),
        "rows": normalized,
        "warnings": [],
    }
    if not payload["sums_to_100pct"]:
        payload["warnings"].append("Draft target weights do not sum to 100%; review draft approval should remain blocked.")
    path = _reports_dir(root_path) / f"{generated_at.strftime('%Y-%m-%dT%H%M%SZ')}.json"
    payload["artifact_path"] = str(path.relative_to(root_path)).replace("\\", "/")
    _atomic_write_json(path, payload)
    return payload

