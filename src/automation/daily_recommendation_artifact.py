"""Daily recommendation artifact V0.

This module creates a durable, read-only-to-consumers strategy action artifact
from existing operational and Strategy Intelligence evidence. Generation is an
explicit write operation; read helpers never create files or mutate state.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategy_intelligence import build_strategy_intelligence_payload


SOURCE = "daily_recommendation_artifact_v0"
ARTIFACT_DIR = Path("data/automation/daily_recommendations")
ACTIONS = {"HOLD", "INCREASE", "REDUCE", "REVIEW"}


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


def daily_recommendation_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def daily_recommendation_artifact_path(root: str | Path, as_of_date: str) -> Path:
    return daily_recommendation_artifact_dir(root) / f"{as_of_date}.json"


def latest_daily_recommendation_artifact_path(root: str | Path) -> Path | None:
    folder = daily_recommendation_artifact_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_daily_recommendation_artifact(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_daily_recommendation_artifact_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "No daily recommendation artifact has been generated yet.",
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
            "message": "Latest daily recommendation artifact is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }


def _evidence_strength(card: dict[str, Any], ml_missing: bool, attribution_missing: bool) -> str:
    raw = str(card.get("evidence_strength") or "").upper()
    missing = bool(card.get("missing_evidence")) or ml_missing or attribution_missing
    if "MISSING" in raw or missing:
        return "MISSING"
    if "WATCH" in raw or "WEAK" in raw:
        return "WEAK"
    if "STRONG" in raw:
        return "STRONG"
    return "PARTIAL"


def _confidence(action: str, evidence: str, ml_missing: bool, attribution_missing: bool) -> str:
    if action == "REVIEW" or ml_missing or attribution_missing or evidence == "MISSING":
        return "REVIEW_REQUIRED"
    if evidence == "STRONG":
        return "HIGH"
    if evidence == "PARTIAL":
        return "MEDIUM"
    return "LOW"


def _action_and_weight(card: dict[str, Any], evidence: str, ml_missing: bool, attribution_missing: bool) -> tuple[str, float | None]:
    current = _safe_number(card.get("current_weight"))
    target = _safe_number(card.get("target_weight"))
    decision = str(card.get("decision_recommendation") or card.get("research_decision") or "").upper()
    review_decisions = {
        "WATCH_ONLY",
        "REJECT_RESEARCH_ONLY",
        "REVIEW_REQUIRED",
        "MISSING_EVIDENCE",
        "ACTIVE_UNALLOCATED_ZERO_WEIGHT",
    }
    if decision in review_decisions:
        return "REVIEW", None
    if ml_missing or attribution_missing or evidence == "MISSING":
        return "HOLD", current
    if target is not None and current is not None and target > current:
        return "INCREASE", target
    if target is not None and current is not None and target < current:
        return "REDUCE", target
    return "HOLD", current


def _reason(card: dict[str, Any], action: str, evidence: str, ml_missing: bool, attribution_missing: bool) -> str:
    decision = str(card.get("decision_recommendation") or card.get("research_decision") or "UNAVAILABLE")
    missing_bits: list[str] = []
    if ml_missing:
        missing_bits.append("ML evidence missing")
    if attribution_missing:
        missing_bits.append("attribution evidence missing")
    if action == "REVIEW":
        suffix = "; ".join(missing_bits) if missing_bits else f"Strategy Intelligence decision is {decision}"
        return f"Review required before changing allocation: {suffix}."
    if action == "INCREASE":
        return f"Existing target weight is above current weight and evidence is {evidence.lower()} without missing ML/attribution flags."
    if action == "REDUCE":
        return f"Existing target weight is below current weight and evidence is {evidence.lower()} without missing ML/attribution flags."
    if missing_bits:
        return f"Hold current exposure because {', '.join(missing_bits)}; no allocation-ready increase evidence."
    return f"Hold current exposure; Strategy Intelligence decision is {decision}."


def _risk_warning(action: str, ml_missing: bool, attribution_missing: bool) -> str | None:
    warnings: list[str] = []
    if ml_missing:
        warnings.append("Missing ML validation evidence")
    if attribution_missing:
        warnings.append("Missing attribution/decomposition evidence")
    if action == "REVIEW" and not warnings:
        warnings.append("Human review required before allocation change")
    return "; ".join(warnings) if warnings else None


def _recommendation_from_card(card: dict[str, Any]) -> dict[str, Any]:
    attribution = card.get("return_attribution_summary") or {}
    ml_status = str(card.get("ml_evidence_status") or card.get("ml_role") or "NOT_AVAILABLE")
    attribution_status = str(attribution.get("status") or "NOT_AVAILABLE")
    ml_missing = "MISSING" in ml_status.upper()
    attribution_missing = "MISSING" in attribution_status.upper()
    evidence = _evidence_strength(card, ml_missing, attribution_missing)
    action, proposed_weight = _action_and_weight(card, evidence, ml_missing, attribution_missing)
    if action not in ACTIONS:
        action = "REVIEW"
        proposed_weight = None
    return {
        "strategy_uid": str(card.get("strategy_uid") or ""),
        "display_name": str(card.get("strategy_name") or card.get("display_name") or card.get("strategy_uid") or ""),
        "current_weight": _safe_number(card.get("current_weight")),
        "recommended_action": action,
        "proposed_weight": proposed_weight,
        "confidence": _confidence(action, evidence, ml_missing, attribution_missing),
        "reason": _reason(card, action, evidence, ml_missing, attribution_missing),
        "evidence_strength": evidence,
        "risk_warning": _risk_warning(action, ml_missing, attribution_missing),
        "ml_evidence_status": ml_status,
        "attribution_status": attribution_status,
        "source_artifacts": card.get("source_artifacts") if isinstance(card.get("source_artifacts"), list) else [],
    }


def build_daily_recommendation_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    as_of_date = generated_at[:10]
    intelligence = strategy_intelligence_payload or build_strategy_intelligence_payload(root_path, now=now)
    cards = intelligence.get("cards") if isinstance(intelligence, dict) else []
    recommendations = [_recommendation_from_card(card) for card in cards or [] if isinstance(card, dict)]
    summary = {
        "increase_count": sum(row["recommended_action"] == "INCREASE" for row in recommendations),
        "reduce_count": sum(row["recommended_action"] == "REDUCE" for row in recommendations),
        "hold_count": sum(row["recommended_action"] == "HOLD" for row in recommendations),
        "review_count": sum(row["recommended_action"] == "REVIEW" for row in recommendations),
        "missing_ml_evidence_count": sum("MISSING" in str(row["ml_evidence_status"]).upper() for row in recommendations),
        "missing_attribution_evidence_count": sum("MISSING" in str(row["attribution_status"]).upper() for row in recommendations),
    }
    warnings: list[str] = []
    if summary["missing_ml_evidence_count"]:
        warnings.append("Missing ML evidence prevents evidence-based INCREASE recommendations.")
    if summary["missing_attribution_evidence_count"]:
        warnings.append("Missing attribution/decomposition evidence prevents evidence-based INCREASE recommendations.")
    if not any(row["proposed_weight"] is not None and row["proposed_weight"] != row["current_weight"] for row in recommendations):
        warnings.append("No allocation-ready proposed weight changes were available; proposed_weight is null or current_weight.")
    return {
        "ok": True,
        "source": SOURCE,
        "generated_at": generated_at,
        "as_of_date": as_of_date,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "strategy_count": len(recommendations) if recommendations else 0,
        "recommendations": recommendations,
        "summary": summary,
        "warnings": warnings,
    }


def write_daily_recommendation_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_daily_recommendation_artifact(
        root_path,
        now=now,
        strategy_intelligence_payload=strategy_intelligence_payload,
    )
    path = daily_recommendation_artifact_path(root_path, payload["as_of_date"])
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
