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
from src.automation.blackbox_decomposition_manifest import build_blackbox_decomposition_manifest
from src.automation.candidate_strategy_identity_bridge import build_candidate_strategy_identity_bridge
from src.automation.daily_cycle import read_latest_daily_cycle_status
from src.automation.daily_recommendation_artifact import read_latest_daily_recommendation_artifact
from src.automation.ml_intelligence_patch_manifest import build_ml_intelligence_patch_manifest
from src.automation.review_draft_eligibility import build_review_draft_eligibility
from src.automation.strategy_factory_evidence_manifest import build_strategy_factory_evidence_manifest
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


def _review_draft_eligibility(root: Path) -> dict[str, Any]:
    payload = build_review_draft_eligibility(root)
    eligibility = payload.get("eligibility") or {}
    required = eligibility.get("required_conditions") or {}
    allowed = eligibility.get("review_draft_generation_allowed")
    blocking = eligibility.get("blocking_conditions") if isinstance(eligibility.get("blocking_conditions"), list) else []
    if required.get("allocation_artifact_available") is False:
        status = "MISSING_ARTIFACT"
    elif allowed is True:
        status = "AVAILABLE"
    elif "MISSING_ML_OR_ATTRIBUTION_EVIDENCE" in blocking:
        status = "REVIEW_REQUIRED"
    else:
        status = "BLOCKED"
    context = payload.get("rebalance_context") or {}
    return {
        "status": status,
        "review_draft_generation_allowed": allowed,
        "reason": eligibility.get("reason"),
        "blocking_conditions": blocking,
        "latest_allocation_artifact": payload.get("latest_allocation_artifact"),
        "required_conditions": required,
        "rebalance_context": context,
        "current_approved_plan_status": context.get("approved_plan_status"),
        "effective_date": context.get("effective_date"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }


def _daily_cycle(root: Path) -> dict[str, Any]:
    latest = read_latest_daily_cycle_status(root)
    cycle = latest.get("daily_cycle") or {}
    return {
        "status": cycle.get("status") or latest.get("status") or "MISSING_ARTIFACT",
        "as_of_date": cycle.get("as_of_date"),
        "last_run_at": cycle.get("last_run_at"),
        "daily_recommendation_status": cycle.get("daily_recommendation_status") or "MISSING_ARTIFACT",
        "allocation_recommendation_status": cycle.get("allocation_recommendation_status") or "MISSING_ARTIFACT",
        "review_draft_eligibility_status": cycle.get("review_draft_eligibility_status") or "MISSING_ARTIFACT",
        "artifact_path": latest.get("artifact_path"),
        "errors": cycle.get("errors") if isinstance(cycle.get("errors"), list) else [],
        "warnings": cycle.get("warnings") if isinstance(cycle.get("warnings"), list) else [],
    }


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


def _strategy_factory(root: Path, alpha: Path) -> dict[str, Any]:
    manifest = build_strategy_factory_evidence_manifest(root, alpha_root=alpha)
    summary = manifest.get("summary") or {}
    status = manifest.get("status") or "NOT_AVAILABLE"
    return {
        "status": status,
        "candidate_registry_status": "MISSING_ARTIFACT" if status == "MISSING_ARTIFACT" else "AVAILABLE",
        "candidate_count": summary.get("candidate_count"),
        "research_card_count": summary.get("research_card_count"),
        "test_spec_count": summary.get("test_spec_count"),
        "evidence_report_count": summary.get("evidence_report_count"),
        "ml_gate_count": summary.get("ml_gate_count"),
        "missing_evidence_count": summary.get("missing_evidence_count"),
        "review_required_count": summary.get("review_required_count"),
        "warnings": manifest.get("warnings") if isinstance(manifest.get("warnings"), list) else [],
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


def _ml_intelligence_patch(root: Path, strategy_payload: dict[str, Any]) -> dict[str, Any]:
    payload = build_ml_intelligence_patch_manifest(root, strategy_cards=strategy_payload.get("cards") or [])
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status") or "NOT_AVAILABLE",
        "candidate_count": summary.get("candidate_count"),
        "ml_gate_count": summary.get("ml_gate_count"),
        "ml_missing_evidence_count": summary.get("ml_missing_evidence_count"),
        "ml_ready_for_experiment_count": summary.get("ml_ready_for_experiment_count"),
        "ml_supported_by_evidence_count": summary.get("ml_supported_by_evidence_count"),
        "ml_overfit_risk_count": summary.get("ml_overfit_risk_count"),
        "ml_leakage_risk_count": summary.get("ml_leakage_risk_count"),
        "strategy_card_match_count": summary.get("strategy_card_match_count"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }


def _identity_bridge(root: Path, strategy_payload: dict[str, Any]) -> dict[str, Any]:
    payload = build_candidate_strategy_identity_bridge(root, strategy_cards=strategy_payload.get("cards") or [])
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status") or "NOT_WIRED",
        "matched_count": summary.get("matched_count"),
        "unmatched_factory_count": summary.get("unmatched_factory_count"),
        "unmatched_strategy_card_count": summary.get("unmatched_strategy_card_count"),
        "activation_lineage_match_count": summary.get("activation_lineage_match_count"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }


def _blackbox_decomposition(root: Path, strategy_payload: dict[str, Any]) -> dict[str, Any]:
    cache_path = root / "data" / "automation" / "blackbox_decomposition" / "manifest.json"
    payload = _read_json(cache_path, {})
    if not isinstance(payload, dict) or payload.get("source") != "blackbox_decomposition_manifest_v0":
        payload = build_blackbox_decomposition_manifest(root, strategy_cards=strategy_payload.get("cards") or [])
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status") or "NOT_WIRED",
        "decomposition_available_count": summary.get("decomposition_available_count"),
        "missing_decomposition_count": summary.get("missing_decomposition_count"),
        "long_short_attribution_count": summary.get("long_short_attribution_count"),
        "factor_exposure_count": summary.get("factor_exposure_count"),
        "sector_exposure_count": summary.get("sector_exposure_count"),
        "regime_evidence_count": summary.get("regime_evidence_count"),
        "cost_sensitivity_count": summary.get("cost_sensitivity_count"),
        "signal_bucket_count": summary.get("signal_bucket_count"),
        "feature_importance_count": summary.get("feature_importance_count"),
        "strategy_card_match_count": summary.get("strategy_card_match_count"),
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }


def _operator_summary(
    daily_cycle: dict[str, Any],
    daily: dict[str, Any],
    allocation: dict[str, Any],
    review_eligibility: dict[str, Any],
    rebalance: dict[str, Any],
    strategy_factory: dict[str, Any],
    identity_bridge: dict[str, Any],
    ml: dict[str, Any],
    ml_patch: dict[str, Any],
    decomposition: dict[str, Any],
    blackbox_decomposition: dict[str, Any],
) -> dict[str, Any]:
    review_items: list[str] = []
    warnings: list[str] = []
    if daily_cycle["status"] in {"MISSING_ARTIFACT", "PARTIAL", "FAILED", "NOT_WIRED"}:
        review_items.append("Daily automation cycle is missing, partial, or failed.")
    if daily["status"] == "MISSING_ARTIFACT":
        review_items.append("Daily recommendation artifact has not been generated.")
    if daily["status"] == "REVIEW_REQUIRED":
        review_items.append("Daily recommendation artifact requires review because evidence is incomplete.")
    if allocation["status"] == "MISSING_ARTIFACT":
        review_items.append("Allocation recommendation artifact has not been generated.")
    if allocation["status"] == "REVIEW_REQUIRED":
        review_items.append("Allocation recommendation artifact is review-required or recommends no allocation change.")
    if review_eligibility["status"] in {"BLOCKED", "REVIEW_REQUIRED", "MISSING_ARTIFACT"}:
        review_items.append("Review draft eligibility is blocked or requires review.")
    if rebalance["apply_due_status"] == "DUE_NOT_APPLIED":
        review_items.append("Approved paper rebalance is due but not applied.")
    if strategy_factory["candidate_registry_status"] != "AVAILABLE":
        review_items.append("Strategy Factory candidate registry is missing or unavailable.")
    if identity_bridge["status"] in {"MISSING_LINEAGE", "NOT_WIRED"}:
        review_items.append("Candidate-to-strategy identity bridge has no canonical lineage matches.")
    if ml["status"] in {"MISSING_EVIDENCE", "MISSING_ARTIFACT"}:
        warnings.append("ML evidence remains missing or unavailable for dashboard intelligence.")
    if ml_patch["status"] in {"MISSING_ARTIFACT", "REVIEW_REQUIRED", "NOT_WIRED"}:
        warnings.append("ML Intelligence Patch requires review or has missing evidence.")
    if decomposition["status"] in {"MISSING_EVIDENCE", "MISSING_ARTIFACT"}:
        warnings.append("Attribution/decomposition evidence remains missing or incomplete.")
    if blackbox_decomposition["status"] in {"MISSING_DECOMPOSITION_EVIDENCE", "REVIEW_REQUIRED", "NOT_WIRED"}:
        warnings.append("Black-box decomposition evidence remains missing or requires review.")
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
    daily_cycle = _daily_cycle(root_path)
    daily = _daily_recommendation(root_path)
    allocation = _allocation_recommendation(root_path)
    review_eligibility = _review_draft_eligibility(root_path)
    rebalance = _rebalance(root_path)
    strategy = _strategy_factory(root_path, alpha)
    intelligence = _strategy_intelligence(root_path)
    ml = _ml_intelligence(alpha, intelligence["payload"])
    ml_patch = _ml_intelligence_patch(root_path, intelligence["payload"])
    identity_bridge = _identity_bridge(root_path, intelligence["payload"])
    decomposition = _decomposition(alpha, intelligence["payload"])
    blackbox_decomposition = _blackbox_decomposition(root_path, intelligence["payload"])
    operator = _operator_summary(
        daily_cycle,
        daily,
        allocation,
        review_eligibility,
        rebalance,
        strategy,
        identity_bridge,
        ml,
        ml_patch,
        decomposition,
        blackbox_decomposition,
    )
    return {
        "ok": True,
        "generated_at": generated_at,
        "source": SOURCE,
        "paper_shadow_only": True,
        "live_trading_enabled": False,
        "financial_state_mutated": False,
        "alpha_research_root": str(alpha),
        "daily_cycle": daily_cycle,
        "daily_recommendation": daily,
        "allocation_recommendation": allocation,
        "review_draft_eligibility": review_eligibility,
        "rebalance": rebalance,
        "strategy_factory": strategy,
        "identity_bridge": identity_bridge,
        "ml_intelligence": ml,
        "ml_intelligence_patch": ml_patch,
        "decomposition": decomposition,
        "blackbox_decomposition": blackbox_decomposition,
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
    daily_cycle = manifest.get("daily_cycle") or {}
    allocation = manifest.get("allocation_recommendation") or {}
    review_eligibility = manifest.get("review_draft_eligibility") or {}
    rebalance = manifest.get("rebalance") or {}
    strategy = manifest.get("strategy_factory") or {}
    identity_bridge = manifest.get("identity_bridge") or {}
    ml = manifest.get("ml_intelligence") or {}
    ml_patch = manifest.get("ml_intelligence_patch") or {}
    decomposition = manifest.get("decomposition") or {}
    blackbox_decomposition = manifest.get("blackbox_decomposition") or {}
    review_required = len(operator.get("top_review_items") or [])
    review_required += int(strategy.get("review_required_count") or 0)
    missing_evidence = int(ml.get("ml_missing_evidence_count") or 0)
    missing_evidence += int(decomposition.get("missing_decomposition_count") or 0)
    missing_evidence += int(blackbox_decomposition.get("missing_decomposition_count") or 0)
    def daily_count(key: str) -> int | None:
        value = daily.get(key)
        return int(value) if value is not None else None

    def compact_count(payload: dict[str, Any], key: str) -> int | None:
        value = payload.get(key)
        return int(value) if value is not None else None

    return {
        "source": SOURCE,
        "overall_status": operator.get("overall_status") or "NOT_AVAILABLE",
        "daily_cycle_status": daily_cycle.get("status") or "NOT_WIRED",
        "daily_cycle_as_of_date": daily_cycle.get("as_of_date"),
        "daily_cycle_last_run_at": daily_cycle.get("last_run_at"),
        "daily_cycle_daily_recommendation_status": daily_cycle.get("daily_recommendation_status"),
        "daily_cycle_allocation_recommendation_status": daily_cycle.get("allocation_recommendation_status"),
        "daily_cycle_review_draft_eligibility_status": daily_cycle.get("review_draft_eligibility_status"),
        "daily_cycle_errors": daily_cycle.get("errors") or [],
        "daily_cycle_warnings": daily_cycle.get("warnings") or [],
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
        "review_draft_eligibility_status": review_eligibility.get("status") or "NOT_WIRED",
        "review_draft_generation_allowed": review_eligibility.get("review_draft_generation_allowed"),
        "review_draft_eligibility_reason": review_eligibility.get("reason"),
        "review_draft_blocking_conditions": review_eligibility.get("blocking_conditions") or [],
        "review_draft_latest_allocation_artifact": review_eligibility.get("latest_allocation_artifact"),
        "review_draft_current_approved_plan_status": review_eligibility.get("current_approved_plan_status"),
        "review_draft_effective_date": review_eligibility.get("effective_date"),
        "rebalance_status": rebalance.get("apply_due_status") or rebalance.get("approved_plan_status") or "NOT_AVAILABLE",
        "strategy_factory_status": strategy.get("status") or "NOT_AVAILABLE",
        "strategy_factory_evidence_status": strategy.get("status") or "NOT_AVAILABLE",
        "strategy_factory_evidence_candidate_count": compact_count(strategy, "candidate_count"),
        "strategy_factory_evidence_research_card_count": compact_count(strategy, "research_card_count"),
        "strategy_factory_evidence_test_spec_count": compact_count(strategy, "test_spec_count"),
        "strategy_factory_evidence_evidence_report_count": compact_count(strategy, "evidence_report_count"),
        "strategy_factory_evidence_ml_gate_count": compact_count(strategy, "ml_gate_count"),
        "strategy_factory_evidence_missing_evidence_count": compact_count(strategy, "missing_evidence_count"),
        "strategy_factory_evidence_review_required_count": compact_count(strategy, "review_required_count"),
        "strategy_factory_evidence_warnings": strategy.get("warnings") or [],
        "identity_bridge_status": identity_bridge.get("status") or "NOT_WIRED",
        "identity_bridge_matched_count": compact_count(identity_bridge, "matched_count"),
        "identity_bridge_unmatched_factory_count": compact_count(identity_bridge, "unmatched_factory_count"),
        "identity_bridge_unmatched_strategy_card_count": compact_count(identity_bridge, "unmatched_strategy_card_count"),
        "identity_bridge_activation_lineage_match_count": compact_count(identity_bridge, "activation_lineage_match_count"),
        "identity_bridge_warnings": identity_bridge.get("warnings") or [],
        "ml_intelligence_status": ml.get("status") or "NOT_AVAILABLE",
        "ml_intelligence_patch_status": ml_patch.get("status") or "NOT_WIRED",
        "ml_intelligence_patch_candidate_count": compact_count(ml_patch, "candidate_count"),
        "ml_intelligence_patch_ml_gate_count": compact_count(ml_patch, "ml_gate_count"),
        "ml_intelligence_patch_missing_evidence_count": compact_count(ml_patch, "ml_missing_evidence_count"),
        "ml_intelligence_patch_ready_for_experiment_count": compact_count(ml_patch, "ml_ready_for_experiment_count"),
        "ml_intelligence_patch_supported_by_evidence_count": compact_count(ml_patch, "ml_supported_by_evidence_count"),
        "ml_intelligence_patch_overfit_risk_count": compact_count(ml_patch, "ml_overfit_risk_count"),
        "ml_intelligence_patch_leakage_risk_count": compact_count(ml_patch, "ml_leakage_risk_count"),
        "ml_intelligence_patch_strategy_card_match_count": compact_count(ml_patch, "strategy_card_match_count"),
        "ml_intelligence_patch_warnings": ml_patch.get("warnings") or [],
        "decomposition_status": decomposition.get("status") or "NOT_AVAILABLE",
        "blackbox_decomposition_status": blackbox_decomposition.get("status") or "NOT_WIRED",
        "blackbox_decomposition_available_count": compact_count(blackbox_decomposition, "decomposition_available_count"),
        "blackbox_missing_decomposition_count": compact_count(blackbox_decomposition, "missing_decomposition_count"),
        "blackbox_long_short_attribution_count": compact_count(blackbox_decomposition, "long_short_attribution_count"),
        "blackbox_factor_exposure_count": compact_count(blackbox_decomposition, "factor_exposure_count"),
        "blackbox_sector_exposure_count": compact_count(blackbox_decomposition, "sector_exposure_count"),
        "blackbox_regime_evidence_count": compact_count(blackbox_decomposition, "regime_evidence_count"),
        "blackbox_cost_sensitivity_count": compact_count(blackbox_decomposition, "cost_sensitivity_count"),
        "blackbox_signal_bucket_count": compact_count(blackbox_decomposition, "signal_bucket_count"),
        "blackbox_feature_importance_count": compact_count(blackbox_decomposition, "feature_importance_count"),
        "blackbox_strategy_card_match_count": compact_count(blackbox_decomposition, "strategy_card_match_count"),
        "blackbox_decomposition_warnings": blackbox_decomposition.get("warnings") or [],
        "review_required_count": review_required,
        "missing_evidence_count": missing_evidence,
        "paper_shadow_only": True,
        "live_trading_enabled": False,
        "financial_state_mutated": False,
    }
