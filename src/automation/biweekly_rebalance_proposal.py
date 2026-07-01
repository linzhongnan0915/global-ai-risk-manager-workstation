"""Biweekly paper rebalance proposal artifact V1.

Builds proposal-only paper target rows from the latest daily allocation
recommendation artifact. It never creates approved plans, paper apply events,
orders, or NAV/P&L mutations.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.daily_allocation_recommendation import read_latest_daily_allocation_recommendation


SOURCE = "biweekly_paper_rebalance_proposal_v1"
SCHEMA_VERSION = "biweekly_rebalance_proposal_v1"
ARTIFACT_DIR = Path("data/automation/biweekly_rebalance_proposals")
BUY_COST_BPS = 5.0
SELL_COST_BPS = 5.0
MATERIAL_TRADE_THRESHOLD = 0.0005


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


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def biweekly_rebalance_proposal_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def biweekly_rebalance_proposal_artifact_path(root: str | Path, proposal_date: str) -> Path:
    return biweekly_rebalance_proposal_artifact_dir(root) / f"{proposal_date}.json"


def latest_biweekly_rebalance_proposal_artifact_path(root: str | Path) -> Path | None:
    folder = biweekly_rebalance_proposal_artifact_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_biweekly_rebalance_proposal(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_biweekly_rebalance_proposal_artifact_path(root_path)
    if path is None:
        return _missing_latest_response(root_path)
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or payload.get("source") != SOURCE:
        return {
            "ok": False,
            "status": "INVALID_ARTIFACT",
            "source": SOURCE,
            "artifact_path": _relative(root_path, path),
            "proposal_only": True,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "paper_apply_created": False,
            "approved_plan_created": False,
            "message": "Latest biweekly rebalance proposal is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "proposal_only": True,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
    }


def _missing_latest_response(root: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "MISSING_ARTIFACT",
        "source": SOURCE,
        "artifact_path": None,
        "proposal_only": True,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "message": "No biweekly paper rebalance proposal artifact has been generated yet.",
    }


def _missing_daily_response(root: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "MISSING_DAILY_ALLOCATION_RECOMMENDATION",
        "source": SOURCE,
        "artifact_path": None,
        "proposal_only": True,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "message": "No daily allocation recommendation artifact exists; biweekly proposal was not fabricated.",
    }


def _identity(row: dict[str, Any]) -> str:
    for key in ("strategy_uid", "internal_id", "strategy_id", "candidate_id"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _is_combined(row: dict[str, Any]) -> bool:
    uid = _identity(row)
    role_text = " ".join(str(row.get(key) or "") for key in ("allocation_role", "strategy_name", "strategy_id", "internal_id")).upper()
    return uid == "COMBINED_PORTFOLIO" or "COMBINED" in role_text or "COMPOSITE" in role_text


def _missing_evidence(row: dict[str, Any]) -> list[str]:
    raw = row.get("missing_evidence")
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if raw:
        return [str(raw)]
    return []


def _cost_bps(delta: float) -> float:
    if delta > 0:
        return BUY_COST_BPS
    if delta < 0:
        return SELL_COST_BPS
    return 0.0


def _proposal_action(row: dict[str, Any], current: float, proposed: float, constraints: list[str]) -> tuple[str, str, float]:
    delta = proposed - current
    role = str(row.get("allocation_role") or "unknown")
    action = str(row.get("action") or "REVIEW")
    missing = _missing_evidence(row)
    if _is_combined(row):
        constraints.append("derived_composite_context_not_tradeable")
        return "REVIEW_ONLY", "Combined Portfolio is a derived context row, not an ordinary tradeable sleeve.", current
    if role == "active_unallocated" and missing:
        constraints.append("active_unallocated_missing_evidence_review_only")
        return "REVIEW_ONLY", "Active-unallocated strategy has missing evidence; no automatic funding proposal is made.", current
    if missing:
        constraints.append("missing_evidence_review_only")
        return "REVIEW_ONLY", "Missing evidence propagated from daily allocation recommendation; row requires review.", current
    if role == "excluded_or_review" or action == "ZERO_WEIGHT":
        constraints.append("excluded_or_review_zero_target")
        return "ZERO_TARGET", "Strategy is excluded or review-only in the daily recommendation; target is zero.", 0.0
    if role == "active_unallocated" and proposed > current:
        constraints.append("active_unallocated_starter_target_from_daily_recommendation")
        return "BUY_INCREASE", "Active-unallocated starter/capped target comes from daily allocation recommendation.", proposed
    if abs(delta) < MATERIAL_TRADE_THRESHOLD:
        constraints.append("below_material_trade_threshold")
        return "NO_TRADE", "Current and recommended weights are within material threshold.", proposed
    if delta > 0:
        return "BUY_INCREASE", "Recommended paper target is above current weight.", proposed
    return "SELL_REDUCE", "Recommended paper target is below current weight.", proposed


def _proposal_row(row: dict[str, Any]) -> dict[str, Any]:
    current = _safe_number(row.get("current_weight"))
    recommended = _safe_number(row.get("recommended_weight"))
    proposed = recommended
    constraints = [str(item) for item in row.get("constraints_applied") or [] if item]
    proposal_action, rationale, proposed = _proposal_action(row, current, proposed, constraints)
    delta = proposed - current
    turnover = abs(delta)
    bps = _cost_bps(delta)
    cost_weight = turnover * bps / 10000.0
    return {
        "strategy_uid": _identity(row),
        "strategy_id": row.get("strategy_id"),
        "internal_id": row.get("internal_id"),
        "strategy_name": row.get("strategy_name") or _identity(row),
        "allocation_role": row.get("allocation_role") or "unknown",
        "current_weight": current,
        "recommended_weight": recommended,
        "proposed_weight": proposed,
        "delta": delta,
        "drift": delta,
        "estimated_turnover": turnover,
        "estimated_transaction_cost_bps": bps,
        "estimated_transaction_cost_weight": cost_weight,
        "action": row.get("action") or "REVIEW",
        "proposal_action": proposal_action,
        "rationale": rationale,
        "evidence_status": row.get("evidence_status") or "MISSING_EVIDENCE",
        "risk_status": row.get("risk_status") or "MISSING_RISK_EVIDENCE",
        "ml_status": row.get("ml_status") or "ML_MISSING_EVIDENCE",
        "attribution_status": row.get("attribution_status") or "Missing Attribution Evidence",
        "missing_evidence": _missing_evidence(row),
        "constraints_applied": list(dict.fromkeys(constraints)),
        "source_artifacts": row.get("source_artifacts") if isinstance(row.get("source_artifacts"), list) else [],
        "paper_state": {
            "proposal_only": True,
            "paper_shadow_only": True,
            "paper_apply_created": False,
            "approved_plan_created": False,
        },
        "live_trading": False,
        "brokerage_execution": False,
    }


def build_biweekly_rebalance_proposal_artifact(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    root_path = Path(root)
    latest = read_latest_daily_allocation_recommendation(root_path)
    if not latest.get("ok"):
        return _missing_daily_response(root_path)
    daily = latest.get("artifact") if isinstance(latest.get("artifact"), dict) else {}
    rows = [_proposal_row(row) for row in daily.get("rows") or [] if isinstance(row, dict) and _identity(row)]
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    proposal_date = generated_at[:10]
    action_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    missing_summary: dict[str, int] = {}
    for row in rows:
        action_counts[row["proposal_action"]] = action_counts.get(row["proposal_action"], 0) + 1
        role_counts[row["allocation_role"]] = role_counts.get(row["allocation_role"], 0) + 1
        for item in row["missing_evidence"]:
            missing_summary[item] = missing_summary.get(item, 0) + 1
    total_turnover = sum(float(row["estimated_turnover"]) for row in rows if row["proposal_action"] != "REVIEW_ONLY")
    total_cost_weight = sum(float(row["estimated_transaction_cost_weight"]) for row in rows if row["proposal_action"] != "REVIEW_ONLY")
    warnings = []
    if action_counts.get("REVIEW_ONLY"):
        warnings.append("Some rows are review-only because evidence or paper state is incomplete.")
    if not rows:
        warnings.append("Daily allocation recommendation contained no proposal rows.")
    next_actions = ["Review proposal rows before any separate accept/apply workflow."]
    if action_counts.get("BUY_INCREASE") or action_counts.get("SELL_REDUCE"):
        next_actions.append("If approved in a future explicit flow, generate a separate paper apply plan; this artifact does not apply trades.")
    return {
        "ok": True,
        "source": SOURCE,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "proposal_date": proposal_date,
        "cadence": "BIWEEKLY",
        "proposal_only": True,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "input_artifacts": {
            "daily_allocation_recommendation": latest.get("artifact_path"),
        },
        "source_daily_allocation_recommendation": {
            "artifact_path": latest.get("artifact_path"),
            "source": daily.get("source"),
            "recommendation_date": daily.get("recommendation_date"),
            "generated_at": daily.get("generated_at"),
        },
        "current_weight_source": "daily_allocation_recommendation.current_weight",
        "proposal_summary": {
            "row_count": len(rows),
            "proposal_action_counts": action_counts,
            "allocation_role_counts": role_counts,
            "total_estimated_turnover": total_turnover,
            "total_estimated_transaction_cost_weight": total_cost_weight,
        },
        "constraints": {
            "cadence": "BIWEEKLY",
            "buy_transaction_cost_bps": BUY_COST_BPS,
            "sell_transaction_cost_bps": SELL_COST_BPS,
            "material_trade_threshold": MATERIAL_TRADE_THRESHOLD,
            "proposed_weight_rule": "recommended_weight unless constrained to review/current or zero target",
            "identity_rule": "strategy_uid/internal_id/strategy_id/candidate_id; display names are UI-only",
            "combined_portfolio_rule": "context/derived composite, not ordinary tradeable row",
        },
        "rows": rows,
        "warnings": warnings,
        "missing_evidence_summary": missing_summary,
        "next_actions": next_actions,
        "labels": {
            "artifact": "Biweekly Paper Rebalance Proposal",
            "mode": "Proposal only",
            "safety": "No approved plan, no paper apply, no NAV/P&L mutation, no live trading",
        },
    }


def write_biweekly_rebalance_proposal_artifact(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_biweekly_rebalance_proposal_artifact(root_path, now=now)
    if not payload.get("ok"):
        return payload
    path = biweekly_rebalance_proposal_artifact_path(root_path, payload["proposal_date"])
    _atomic_write_json(path, payload)
    return {
        "ok": True,
        "status": "GENERATED",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "proposal_only": True,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
    }
