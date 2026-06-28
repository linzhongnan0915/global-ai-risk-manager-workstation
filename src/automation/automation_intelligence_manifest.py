"""Read-only Automation Intelligence Manifest V0.

This module summarizes existing local automation, paper-rebalance, Strategy
Factory, ML, decomposition, and Strategy Intelligence artifacts. It never writes
files, mutates financial state, runs research, trains models, or applies plans.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.allocation_recommendation_artifact import read_latest_allocation_recommendation_artifact
from src.automation.daily_recommendation_artifact import read_latest_daily_recommendation_artifact
from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.strategy_intelligence import build_strategy_intelligence_payload


SOURCE = "automation_intelligence_manifest_v0"
ALPHA_RESEARCH_ENV = "STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _relative_or_abs(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _alpha_root() -> Path:
    configured = os.environ.get(ALPHA_RESEARCH_ENV)
    if configured:
        return Path(configured)
    return Path(r"D:\Global_Ai\alpha_research")


def _latest_collection_item(path: Path, key: str) -> dict[str, Any] | None:
    payload = _read_json(path, {})
    rows = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    latest = rows[-1]
    return latest if isinstance(latest, dict) else None


def _daily_recommendation(root: Path) -> dict[str, Any]:
    latest = read_latest_daily_recommendation_artifact(root)
    if not latest.get("ok"):
        return {
            "status": "MISSING_ARTIFACT",
            "artifact_path": None,
            "latest_generated_at": None,
            "strategy_count": None,
            "recommendation_count": None,
            "increase_count": None,
            "reduce_count": None,
            "hold_count": None,
            "review_count": None,
            "missing_ml_evidence_count": None,
            "missing_attribution_evidence_count": None,
            "warnings": [latest.get("message") or "Daily recommendation artifact has not been generated."],
            "reason": "Generate the daily recommendation artifact with the explicit POST endpoint.",
            "preview": [],
        }
    payload = latest.get("artifact") or {}
    rows = payload.get("recommendations") if isinstance(payload, dict) else []
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    review_count = int((summary or {}).get("review_count") or 0)
    recommendation_count = len(rows) if isinstance(rows, list) else 0
    missing_count = int((summary or {}).get("missing_ml_evidence_count") or 0) + int(
        (summary or {}).get("missing_attribution_evidence_count") or 0
    )
    status = "AVAILABLE"
    if recommendation_count and (review_count / recommendation_count >= 0.5 or missing_count >= recommendation_count):
        status = "REVIEW_REQUIRED"
    return {
        "status": status,
        "artifact_path": latest.get("artifact_path"),
        "latest_generated_at": payload.get("generated_at"),
        "as_of_date": payload.get("as_of_date"),
        "strategy_count": recommendation_count,
        "recommendation_count": recommendation_count,
        "increase_count": int((summary or {}).get("increase_count") or 0),
        "reduce_count": int((summary or {}).get("reduce_count") or 0),
        "hold_count": int((summary or {}).get("hold_count") or 0),
        "review_count": review_count,
        "missing_ml_evidence_count": (summary or {}).get("missing_ml_evidence_count"),
        "missing_attribution_evidence_count": (summary or {}).get("missing_attribution_evidence_count"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "reason": _daily_recommendation_reason(status, summary or {}, payload.get("warnings") or []),
        "preview": _daily_recommendation_preview(rows if isinstance(rows, list) else []),
    }


def _daily_recommendation_reason(status: str, summary: dict[str, Any], warnings: list[Any]) -> str:
    if status == "REVIEW_REQUIRED":
        return "Daily artifact exists, but review or missing-evidence rows dominate today's actions."
    if warnings:
        return str(warnings[0])
    total = sum(int(summary.get(key) or 0) for key in ("increase_count", "reduce_count", "hold_count", "review_count"))
    return f"Daily artifact exists with {total} backend-generated recommendation rows."


def _daily_recommendation_preview(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        preview.append(
            {
                "strategy_uid": row.get("strategy_uid"),
                "display_name": row.get("display_name"),
                "recommended_action": row.get("recommended_action"),
                "reason": row.get("reason"),
                "missing_evidence_label": row.get("risk_warning"),
                "evidence_strength": row.get("evidence_strength"),
            }
        )
    return preview


def _allocation_recommendation(root: Path) -> dict[str, Any]:
    latest = read_latest_allocation_recommendation_artifact(root)
    if not latest.get("ok"):
        return {
            "status": "MISSING_ARTIFACT",
            "artifact_path": None,
            "allocation_change_recommended": None,
            "no_change_count": None,
            "review_required_count": None,
            "increase_candidate_count": None,
            "reduce_candidate_count": None,
            "allocation_integrity": None,
            "warnings": [latest.get("message") or "Allocation recommendation artifact has not been generated."],
            "reason": "Generate the allocation recommendation artifact with the explicit POST endpoint.",
            "preview": [],
        }
    payload = latest.get("artifact") or {}
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    rows = payload.get("recommendations") if isinstance(payload, dict) else []
    integrity = payload.get("allocation_integrity") if isinstance(payload, dict) else {}
    review_count = int((summary or {}).get("review_required_count") or 0)
    status = "AVAILABLE"
    if review_count or not bool((summary or {}).get("allocation_change_recommended")):
        status = "REVIEW_REQUIRED"
    return {
        "status": status,
        "artifact_path": latest.get("artifact_path"),
        "allocation_change_recommended": (summary or {}).get("allocation_change_recommended"),
        "no_change_count": (summary or {}).get("no_change_count"),
        "review_required_count": (summary or {}).get("review_required_count"),
        "increase_candidate_count": (summary or {}).get("increase_candidate_count"),
        "reduce_candidate_count": (summary or {}).get("reduce_candidate_count"),
        "allocation_integrity": integrity,
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "reason": _allocation_recommendation_reason(status, summary or {}, integrity or {}, payload.get("warnings") or []),
        "preview": _allocation_recommendation_preview(rows if isinstance(rows, list) else []),
    }


def _allocation_recommendation_reason(
    status: str,
    summary: dict[str, Any],
    integrity: dict[str, Any],
    warnings: list[Any],
) -> str:
    if integrity.get("sums_to_100pct") is not True:
        return "Allocation artifact cannot prove proposed weights sum to 100%; review draft generation is blocked."
    if status == "REVIEW_REQUIRED":
        return "Allocation artifact is available, but evidence-gated review or NO_CHANGE dominates today's guidance."
    if warnings:
        return str(warnings[0])
    return "Allocation artifact exists and proposed target weights pass the 100% integrity check."


def _allocation_recommendation_preview(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        preview.append(
            {
                "strategy_uid": row.get("strategy_uid"),
                "display_name": row.get("display_name"),
                "allocation_action": row.get("allocation_action"),
                "current_weight": row.get("current_weight"),
                "proposed_weight": row.get("proposed_weight"),
                "reason": row.get("reason"),
            }
        )
    return preview


def _apply_due_status(latest_plan: dict[str, Any], applied_events: list[dict[str, Any]]) -> tuple[str, bool, str | None]:
    if not latest_plan:
        return "NOT_AVAILABLE", False, None
    status = str(latest_plan.get("status") or "REVIEW_REQUIRED")
    effective_date = latest_plan.get("effective_date")
    plan_id = latest_plan.get("plan_id")
    if status == "APPLIED_PAPER" or any(event.get("plan_id") == plan_id for event in applied_events):
        return "ALREADY_APPLIED", False, effective_date
    if status != "APPROVED_WAITING_EFFECTIVE_DATE":
        return "REVIEW_REQUIRED", False, effective_date
    today = datetime.now(timezone.utc).date().isoformat()
    if effective_date and str(effective_date)[:10] <= today:
        return "DUE_NOT_APPLIED", True, effective_date
    return "NOT_DUE", False, effective_date


def _rebalance(root: Path) -> dict[str, Any]:
    paper = paper_rebalance_snapshot_payload(root)
    monthly = (paper.get("monthly_proposal") or {}).get("latest_proposal") or {}
    review = (paper.get("recommendation_review") or {}).get("latest_draft") or {}
    approved = paper.get("approved_rebalance") or {}
    latest_plan = approved.get("latest_plan") or {}
    applied_events = approved.get("applied_events") or []
    apply_due, safe_to_apply, effective_date = _apply_due_status(latest_plan, applied_events)
    return {
        "monthly_proposal_status": monthly.get("status") or "MISSING_ARTIFACT",
        "review_draft_status": review.get("status") or review.get("review_status") or "MISSING_ARTIFACT",
        "approved_plan_status": latest_plan.get("status") or "MISSING_ARTIFACT",
        "apply_due_status": apply_due,
        "effective_date": effective_date,
        "safe_to_apply_now": bool(safe_to_apply),
        "mutation_allowed_from_get": False,
    }


def _strategy_factory(alpha: Path) -> dict[str, Any]:
    sf = alpha / "strategy_factory"
    if not sf.exists():
        return {
            "status": "MISSING_ARTIFACT",
            "candidate_registry_status": "MISSING_ARTIFACT",
            "research_card_count": None,
            "test_spec_count": None,
            "evidence_report_count": None,
            "review_required_count": None,
        }
    registry_paths = list((sf / "candidate_results").glob("*candidate*registry*.json"))
    research_cards = list((sf / "research_cards").glob("*.md"))
    test_specs = list((sf / "codex_test_specs").glob("*.md"))
    evidence_reports = list((sf / "evidence_reports").glob("*/evidence_report.md"))
    review_required = 0
    for registry_path in registry_paths:
        payload = _read_json(registry_path, {})
        for candidate in payload.get("candidates", []) if isinstance(payload, dict) else []:
            decision = str((candidate or {}).get("decision") or "").upper()
            eligible = bool((candidate or {}).get("candidate_portfolio_eligible"))
            if decision in {"WATCH_ONLY", "BLOCKED_NEEDS_BOSS_API", "REJECTED"} or not eligible:
                review_required += 1
    return {
        "status": "AVAILABLE",
        "candidate_registry_status": "AVAILABLE" if registry_paths else "MISSING_ARTIFACT",
        "research_card_count": len(research_cards),
        "test_spec_count": len(test_specs),
        "evidence_report_count": len(evidence_reports),
        "review_required_count": review_required if registry_paths else None,
    }


def _ml_intelligence(alpha: Path, strategy_payload: dict[str, Any]) -> dict[str, Any]:
    artifact_paths = sorted(alpha.glob("**/ml_diagnostics_summary.json")) if alpha.exists() else []
    supported = rejected = overfit = missing = 0
    for path in artifact_paths:
        payload = _read_json(path, {})
        text = json.dumps(payload, sort_keys=True).upper()
        if "LEAKAGE_FAIL" in text or "REJECT" in text or "BLOCKED_DATA" in text:
            rejected += 1
        if "OVERFIT" in text and ("HIGH" in text or "BLOCKING" in text):
            overfit += 1
        if "MISSING_EVIDENCE" in text or "INSUFFICIENT" in text:
            missing += 1
        else:
            supported += 1
    si_summary = strategy_payload.get("summary") or {}
    si_missing = si_summary.get("ml_missing_evidence_count")
    if not artifact_paths and si_missing is not None:
        missing = int(si_missing)
    status = "AVAILABLE" if artifact_paths else ("MISSING_EVIDENCE" if missing else "MISSING_ARTIFACT")
    return {
        "status": status,
        "ml_gate_available": bool(artifact_paths),
        "ml_supported_count": supported if artifact_paths else 0,
        "ml_missing_evidence_count": missing,
        "ml_rejected_count": rejected if artifact_paths else 0,
        "ml_overfit_risk_count": overfit if artifact_paths else 0,
        "artifact_paths": [_relative_or_abs(alpha, path) for path in artifact_paths[:50]],
    }


def _decomposition(alpha: Path, strategy_payload: dict[str, Any]) -> dict[str, Any]:
    patterns = ["*attribution*.csv", "*decomposition*.csv", "*decomposition*.md"]
    paths: list[Path] = []
    if alpha.exists():
        for pattern in patterns:
            paths.extend(alpha.glob(f"**/{pattern}"))
    unique = sorted({path.resolve(): path for path in paths}.values(), key=lambda path: path.as_posix())
    lower_names = [path.name.lower() for path in unique]
    long_short = sum("long_short" in name or "leg_attribution" in name for name in lower_names)
    factor = sum("factor" in name for name in lower_names)
    sector = sum("sector" in name for name in lower_names)
    regime = sum("regime" in name for name in lower_names)
    si_summary = strategy_payload.get("summary") or {}
    missing = int(si_summary.get("missing_attribution_count") or 0)
    return {
        "status": "AVAILABLE" if unique else ("MISSING_EVIDENCE" if missing else "MISSING_ARTIFACT"),
        "attribution_artifact_count": len(unique),
        "long_short_available_count": long_short,
        "factor_exposure_available_count": factor,
        "sector_exposure_available_count": sector,
        "regime_available_count": regime,
        "missing_decomposition_count": missing,
        "artifact_paths": [_relative_or_abs(alpha, path) for path in unique[:50]],
    }


def _strategy_intelligence(root: Path) -> dict[str, Any]:
    payload = build_strategy_intelligence_payload(root)
    cards = payload.get("cards") or []
    ml_visible = any(card.get("ml_role") != "ML_MISSING_EVIDENCE" for card in cards)
    attribution_visible = any(
        (card.get("return_attribution_summary") or {}).get("status") != "Missing Attribution Evidence"
        for card in cards
    )
    missing_visible = any(card.get("missing_evidence") for card in cards)
    return {
        "payload": payload,
        "summary": {
            "card_count": len(cards),
            "ml_evidence_visible": ml_visible,
            "attribution_evidence_visible": attribution_visible,
            "missing_evidence_visible": missing_visible,
        },
    }


def _operator_summary(
    daily: dict[str, Any],
    allocation: dict[str, Any],
    rebalance: dict[str, Any],
    strategy_factory: dict[str, Any],
    ml: dict[str, Any],
    decomposition: dict[str, Any],
) -> dict[str, Any]:
    review_items: list[str] = []
    warnings: list[str] = []
    if daily["status"] == "MISSING_ARTIFACT":
        review_items.append("Daily recommendation artifact has not been generated.")
    if daily["status"] == "REVIEW_REQUIRED":
        review_items.append("Daily recommendation artifact requires review because evidence is incomplete.")
    if allocation["status"] == "MISSING_ARTIFACT":
        review_items.append("Allocation recommendation artifact has not been generated.")
    if allocation["status"] == "REVIEW_REQUIRED":
        review_items.append("Allocation recommendation artifact is review-required or recommends no allocation change.")
    if rebalance["apply_due_status"] == "DUE_NOT_APPLIED":
        review_items.append("Approved paper rebalance is due but not applied.")
    if strategy_factory["candidate_registry_status"] != "AVAILABLE":
        review_items.append("Strategy Factory candidate registry is missing or unavailable.")
    if ml["status"] in {"MISSING_EVIDENCE", "MISSING_ARTIFACT"}:
        warnings.append("ML evidence remains missing or unavailable for dashboard intelligence.")
    if decomposition["status"] in {"MISSING_EVIDENCE", "MISSING_ARTIFACT"}:
        warnings.append("Attribution/decomposition evidence remains missing or incomplete.")
    if rebalance["safe_to_apply_now"]:
        overall = "REVIEW_REQUIRED"
    elif daily["status"] == "MISSING_ARTIFACT":
        overall = "MISSING_ARTIFACT"
    elif review_items or warnings:
        overall = "REVIEW_REQUIRED"
    else:
        overall = "OK"
    return {
        "overall_status": overall,
        "top_review_items": review_items[:8],
        "warnings": warnings[:8],
    }


def build_automation_intelligence_manifest(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    root_path = Path(root)
    alpha = _alpha_root()
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    daily = _daily_recommendation(root_path)
    allocation = _allocation_recommendation(root_path)
    rebalance = _rebalance(root_path)
    strategy = _strategy_factory(alpha)
    intelligence = _strategy_intelligence(root_path)
    ml = _ml_intelligence(alpha, intelligence["payload"])
    decomposition = _decomposition(alpha, intelligence["payload"])
    operator = _operator_summary(daily, allocation, rebalance, strategy, ml, decomposition)
    return {
        "ok": True,
        "generated_at": generated_at,
        "source": SOURCE,
        "paper_shadow_only": True,
        "live_trading_enabled": False,
        "financial_state_mutated": False,
        "alpha_research_root": str(alpha),
        "daily_recommendation": daily,
        "allocation_recommendation": allocation,
        "rebalance": rebalance,
        "strategy_factory": strategy,
        "ml_intelligence": ml,
        "decomposition": decomposition,
        "strategy_intelligence": intelligence["summary"],
        "operator_summary": operator,
        "safety": {
            "read_only": True,
            "get_mutates_state": False,
            "nav_pnl_mutation": False,
            "accounting_mutation": False,
            "rebalance_apply_mutation": False,
            "live_brokerage": False,
            "live_fills": False,
        },
    }


def compact_automation_intelligence_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    operator = manifest.get("operator_summary") or {}
    daily = manifest.get("daily_recommendation") or {}
    allocation = manifest.get("allocation_recommendation") or {}
    rebalance = manifest.get("rebalance") or {}
    strategy = manifest.get("strategy_factory") or {}
    ml = manifest.get("ml_intelligence") or {}
    decomposition = manifest.get("decomposition") or {}
    review_required = len(operator.get("top_review_items") or [])
    review_required += int(strategy.get("review_required_count") or 0)
    missing_evidence = int(ml.get("ml_missing_evidence_count") or 0)
    missing_evidence += int(decomposition.get("missing_decomposition_count") or 0)
    def daily_count(key: str) -> int | None:
        value = daily.get(key)
        return int(value) if value is not None else None

    def compact_count(payload: dict[str, Any], key: str) -> int | None:
        value = payload.get(key)
        return int(value) if value is not None else None

    return {
        "source": SOURCE,
        "overall_status": operator.get("overall_status") or "NOT_AVAILABLE",
        "daily_recommendation_status": daily.get("status") or "NOT_AVAILABLE",
        "daily_recommendation_count": daily_count("recommendation_count"),
        "daily_recommendation_increase_count": daily_count("increase_count"),
        "daily_recommendation_reduce_count": daily_count("reduce_count"),
        "daily_recommendation_hold_count": daily_count("hold_count"),
        "daily_recommendation_review_count": daily_count("review_count"),
        "daily_recommendation_reason": daily.get("reason"),
        "daily_recommendation_preview": daily.get("preview") or [],
        "allocation_recommendation_status": allocation.get("status") or "NOT_AVAILABLE",
        "allocation_recommendation_no_change_count": compact_count(allocation, "no_change_count"),
        "allocation_recommendation_review_required_count": compact_count(allocation, "review_required_count"),
        "allocation_recommendation_increase_candidate_count": compact_count(allocation, "increase_candidate_count"),
        "allocation_recommendation_reduce_candidate_count": compact_count(allocation, "reduce_candidate_count"),
        "allocation_recommendation_change_recommended": allocation.get("allocation_change_recommended"),
        "allocation_recommendation_reason": allocation.get("reason"),
        "allocation_recommendation_preview": allocation.get("preview") or [],
        "allocation_integrity": allocation.get("allocation_integrity"),
        "rebalance_status": rebalance.get("apply_due_status") or rebalance.get("approved_plan_status") or "NOT_AVAILABLE",
        "strategy_factory_status": strategy.get("status") or "NOT_AVAILABLE",
        "ml_intelligence_status": ml.get("status") or "NOT_AVAILABLE",
        "decomposition_status": decomposition.get("status") or "NOT_AVAILABLE",
        "review_required_count": review_required,
        "missing_evidence_count": missing_evidence,
        "paper_shadow_only": True,
        "live_trading_enabled": False,
        "financial_state_mutated": False,
    }
