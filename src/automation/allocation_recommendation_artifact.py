"""Allocation recommendation artifact V0.

This module translates daily strategy actions into conservative allocation
guidance. It is not an optimizer and never creates rebalance plans or mutates
financial state.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.daily_recommendation_artifact import read_latest_daily_recommendation_artifact


SOURCE = "allocation_recommendation_artifact_v0"
ARTIFACT_DIR = Path("data/automation/allocation_recommendations")
WEIGHT_SUM_TARGET = 1.0
WEIGHT_SUM_TOLERANCE = 0.000001


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _safe_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def allocation_recommendation_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def allocation_recommendation_artifact_path(root: str | Path, as_of_date: str) -> Path:
    return allocation_recommendation_artifact_dir(root) / f"{as_of_date}.json"


def latest_allocation_recommendation_artifact_path(root: str | Path) -> Path | None:
    folder = allocation_recommendation_artifact_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_allocation_recommendation_artifact(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_allocation_recommendation_artifact_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "No allocation recommendation artifact has been generated yet.",
        }
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or payload.get("source") != SOURCE:
        return {
            "ok": False,
            "status": "INVALID_ARTIFACT",
            "source": SOURCE,
            "artifact_path": _relative(root_path, path),
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "Latest allocation recommendation artifact is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }


def _daily_rows_by_uid(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    latest = read_latest_daily_recommendation_artifact(root)
    if not latest.get("ok"):
        return {}, latest
    artifact = latest.get("artifact") or {}
    rows = artifact.get("recommendations") if isinstance(artifact, dict) else []
    by_uid = {
        str(row.get("strategy_uid")): row
        for row in rows or []
        if isinstance(row, dict) and row.get("strategy_uid")
    }
    return by_uid, latest


def _is_included_top_level_sleeve(card: dict[str, Any]) -> bool:
    current = _safe_number(card.get("current_weight"))
    if current is None or current <= 0:
        return False
    return str(card.get("source_status") or "") == "CANONICAL_OPERATIONAL"


def _evidence_missing(card: dict[str, Any], daily: dict[str, Any] | None) -> tuple[bool, list[str]]:
    missing: list[str] = []
    ml_status = str((card.get("ml_evidence") or {}).get("status") or card.get("ml_evidence_status") or "")
    decomp_status = str((card.get("decomposition_evidence") or {}).get("status") or "")
    daily_warning = str((daily or {}).get("risk_warning") or "")
    if "MISSING" in ml_status.upper() or "ML" in daily_warning.upper():
        missing.append("Missing ML Evidence")
    if "MISSING" in decomp_status.upper() or "ATTRIBUTION" in daily_warning.upper():
        missing.append("Missing Attribution Evidence")
    return bool(missing), missing


def _allocation_action(card: dict[str, Any], daily: dict[str, Any] | None, included: bool) -> tuple[str, list[str], str]:
    daily_action = str((daily or {}).get("recommended_action") or "NOT_AVAILABLE")
    missing, blocking = _evidence_missing(card, daily)
    if daily_action == "REVIEW":
        return "REVIEW_REQUIRED", blocking, "Daily recommendation requires review before allocation change."
    if daily_action == "INCREASE" and missing:
        return (
            "REVIEW_REQUIRED",
            blocking,
            "Increase action is blocked because ML or attribution evidence is missing.",
        )
    if daily_action == "REDUCE" and included and not missing:
        return "REDUCE_CANDIDATE", blocking, "Daily recommendation indicates possible reduction; review required before rebalance."
    if daily_action == "INCREASE" and included and not missing:
        return "INCREASE_CANDIDATE", blocking, "Daily recommendation indicates possible increase; review required before rebalance."
    if not included:
        return "REVIEW_REQUIRED" if daily_action == "REVIEW" else "NO_CHANGE", blocking, "Not included in current top-level allocation denominator."
    if missing:
        return "NO_CHANGE", blocking, "Allocation weights not changed because evidence or allocation logic is incomplete."
    return "NO_CHANGE", blocking, "No allocation change recommended from current backend evidence."


def _recommendation_from_card(
    card: dict[str, Any],
    daily: dict[str, Any] | None,
    included: bool,
) -> dict[str, Any]:
    current = _safe_number(card.get("current_weight"))
    allocation_action, blocking, reason = _allocation_action(card, daily, included)
    allocation_change = allocation_action in {"INCREASE_CANDIDATE", "REDUCE_CANDIDATE"}
    proposed = None if current is None else current
    delta = None if proposed is None or current is None else proposed - current
    if not allocation_change and "Allocation weights not changed because evidence or allocation logic is incomplete." not in reason:
        daily_reason = (daily or {}).get("reason")
        if daily_reason and blocking:
            reason = f"{daily_reason} Allocation weights not changed because evidence or allocation logic is incomplete."
    return {
        "strategy_uid": str(card.get("strategy_uid") or ""),
        "display_name": str(card.get("strategy_name") or card.get("strategy_uid") or ""),
        "current_weight": current,
        "daily_action": str((daily or {}).get("recommended_action") or "NOT_AVAILABLE"),
        "allocation_action": allocation_action,
        "allocation_change_recommended": allocation_change,
        "included_in_allocation_denominator": included,
        "proposed_weight": proposed,
        "weight_delta": delta,
        "confidence": "REVIEW_REQUIRED" if allocation_action == "REVIEW_REQUIRED" or blocking else "LOW",
        "reason": reason,
        "blocking_evidence": blocking,
        "risk_warning": (daily or {}).get("risk_warning") or ("; ".join(blocking) if blocking else None),
        "source_artifacts": (daily or {}).get("source_artifacts") if isinstance((daily or {}).get("source_artifacts"), list) else [],
    }


def _allocation_integrity(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    included = [row for row in recommendations if row.get("included_in_allocation_denominator")]
    excluded = [row for row in recommendations if not row.get("included_in_allocation_denominator")]
    proposed = [row.get("proposed_weight") for row in included]
    warnings: list[str] = []
    if not included:
        warnings.append("No included top-level allocation sleeves were available from backend identity.")
        target_sum = None
        sums = None
        residual = None
    elif any(value is None for value in proposed):
        warnings.append("Cannot prove target allocation sums to 100% because at least one included proposed_weight is null.")
        target_sum = None
        sums = None
        residual = None
    else:
        target_sum = sum(float(value) for value in proposed)
        residual = WEIGHT_SUM_TARGET - target_sum
        sums = abs(residual) <= WEIGHT_SUM_TOLERANCE
        if not sums:
            warnings.append("Proposed allocation weights do not sum to 100%; downstream review draft generation is blocked.")
    return {
        "target_weight_sum": target_sum,
        "weight_sum_target": WEIGHT_SUM_TARGET,
        "weight_sum_tolerance": WEIGHT_SUM_TOLERANCE,
        "sums_to_100pct": sums,
        "residual_weight": residual,
        "denominator_source": "strategy_intelligence_current_top_level_canonical_operational_current_weight",
        "included_strategy_count": len(included) if included else 0,
        "excluded_strategy_count": len(excluded),
        "warnings": warnings,
    }


def build_allocation_recommendation_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.strategy_intelligence import build_strategy_intelligence_payload

    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    as_of_date = generated_at[:10]
    intelligence = strategy_intelligence_payload or build_strategy_intelligence_payload(root_path, now=now)
    cards = intelligence.get("cards") if isinstance(intelligence, dict) else []
    daily_by_uid, daily_latest = _daily_rows_by_uid(root_path)
    recommendations = [
        _recommendation_from_card(card, daily_by_uid.get(str(card.get("strategy_uid") or "")), _is_included_top_level_sleeve(card))
        for card in cards or []
        if isinstance(card, dict)
    ]
    integrity = _allocation_integrity(recommendations)
    change_count = sum(bool(row.get("allocation_change_recommended")) for row in recommendations)
    allocation_change_recommended = bool(change_count) and integrity.get("sums_to_100pct") is True
    warnings: list[str] = []
    if not daily_latest.get("ok"):
        warnings.append("Daily recommendation artifact is missing; allocation recommendation uses NOT_AVAILABLE daily actions.")
    if not allocation_change_recommended:
        warnings.append("Allocation weights not changed because evidence or allocation logic is incomplete.")
    warnings.extend(integrity.get("warnings") or [])
    summary = {
        "strategy_count": len(recommendations) if recommendations else 0,
        "no_change_count": sum(row["allocation_action"] == "NO_CHANGE" for row in recommendations),
        "review_required_count": sum(row["allocation_action"] == "REVIEW_REQUIRED" for row in recommendations),
        "increase_candidate_count": sum(row["allocation_action"] == "INCREASE_CANDIDATE" for row in recommendations),
        "reduce_candidate_count": sum(row["allocation_action"] == "REDUCE_CANDIDATE" for row in recommendations),
        "missing_ml_evidence_count": sum("Missing ML Evidence" in row["blocking_evidence"] for row in recommendations),
        "missing_attribution_evidence_count": sum("Missing Attribution Evidence" in row["blocking_evidence"] for row in recommendations),
        "allocation_change_recommended": allocation_change_recommended,
        "review_draft_generation_allowed": allocation_change_recommended and integrity.get("sums_to_100pct") is True,
    }
    return {
        "ok": True,
        "source": SOURCE,
        "generated_at": generated_at,
        "as_of_date": as_of_date,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "optimizer_used": False,
        "rebalance_plan_created": False,
        "rebalance_plan_approved": False,
        "summary": summary,
        "allocation_integrity": integrity,
        "recommendations": recommendations,
        "warnings": warnings,
    }


def write_allocation_recommendation_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_allocation_recommendation_artifact(
        root_path,
        now=now,
        strategy_intelligence_payload=strategy_intelligence_payload,
    )
    path = allocation_recommendation_artifact_path(root_path, payload["as_of_date"])
    _atomic_write_json(path, payload)
    return {
        "ok": True,
        "status": "GENERATED",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }
