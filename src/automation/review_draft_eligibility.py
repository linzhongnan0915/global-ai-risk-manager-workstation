"""Review draft eligibility for allocation recommendation artifacts.

Read helpers in this module do not create review drafts, approved plans, paper
plans, or NAV/P&L state. The optional write helper is gated by the same
eligibility object and returns blocked without writing when conditions fail.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.allocation_recommendation_artifact import read_latest_allocation_recommendation_artifact
from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.market.recommendation_review_draft import create_recommendation_review_draft
from src.reporting.operational_snapshot import load_operational_snapshot_for_response


SOURCE = "review_draft_eligibility_v0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rebalance_context(root: Path) -> dict[str, Any]:
    paper = paper_rebalance_snapshot_payload(root)
    monthly = (paper.get("monthly_proposal") or {}).get("latest_proposal") or {}
    review = (paper.get("recommendation_review") or {}).get("latest_draft") or {}
    approved = paper.get("approved_rebalance") or {}
    latest_plan = approved.get("latest_plan") or {}
    return {
        "monthly_proposal_status": monthly.get("status") or "MISSING_ARTIFACT",
        "review_draft_status": review.get("status") or review.get("review_status") or "MISSING_ARTIFACT",
        "approved_plan_status": latest_plan.get("status") or "MISSING_ARTIFACT",
        "apply_due_status": (paper.get("automation") or {}).get("apply_due_status")
        or _apply_due_status(latest_plan, approved.get("applied_events") or []),
        "effective_date": latest_plan.get("effective_date"),
    }


def _apply_due_status(latest_plan: dict[str, Any], applied_events: list[dict[str, Any]]) -> str:
    if not latest_plan:
        return "NOT_AVAILABLE"
    plan_id = latest_plan.get("plan_id")
    if latest_plan.get("status") == "APPLIED_PAPER" or any(event.get("plan_id") == plan_id for event in applied_events):
        return "ALREADY_APPLIED"
    if latest_plan.get("status") == "APPROVED_WAITING_EFFECTIVE_DATE":
        return "DUE_OR_PENDING_APPROVED_PLAN"
    return "REVIEW_REQUIRED"


def _pending_approved_plan_conflict(context: dict[str, Any]) -> bool:
    return context.get("approved_plan_status") == "APPROVED_WAITING_EFFECTIVE_DATE" and context.get(
        "apply_due_status"
    ) != "ALREADY_APPLIED"


def _missing_evidence_count(summary: dict[str, Any]) -> int:
    return int(summary.get("missing_ml_evidence_count") or 0) + int(
        summary.get("missing_attribution_evidence_count") or 0
    )


def _has_row_blocking_evidence(rows: list[dict[str, Any]]) -> bool:
    return any(row.get("blocking_evidence") for row in rows if isinstance(row, dict))


def build_review_draft_eligibility(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    latest = read_latest_allocation_recommendation_artifact(root_path)
    context = _rebalance_context(root_path)
    blocking: list[str] = []
    warnings: list[str] = []

    if not latest.get("ok"):
        required = {
            "allocation_artifact_available": False,
            "sums_to_100pct": None,
            "allocation_change_recommended": None,
            "no_blocking_missing_evidence": False,
            "no_existing_pending_approved_plan_conflict": not _pending_approved_plan_conflict(context),
        }
        blocking.append("ALLOCATION_RECOMMENDATION_ARTIFACT_MISSING")
        return {
            "source": SOURCE,
            "generated_at": generated_at,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "latest_allocation_artifact": None,
            "eligibility": {
                "review_draft_generation_allowed": False,
                "reason": "Allocation recommendation artifact is missing; review draft generation is blocked.",
                "blocking_conditions": blocking,
                "required_conditions": required,
            },
            "rebalance_context": context,
            "warnings": [latest.get("message") or "Allocation recommendation artifact has not been generated."],
        }

    artifact = latest.get("artifact") or {}
    summary = artifact.get("summary") if isinstance(artifact, dict) else {}
    integrity = artifact.get("allocation_integrity") if isinstance(artifact, dict) else {}
    rows = artifact.get("recommendations") if isinstance(artifact, dict) else []
    rows = rows if isinstance(rows, list) else []
    allocation_change = (summary or {}).get("allocation_change_recommended")
    sums_to_100pct = (integrity or {}).get("sums_to_100pct")
    no_missing = _missing_evidence_count(summary or {}) == 0 and not _has_row_blocking_evidence(rows)
    no_plan_conflict = not _pending_approved_plan_conflict(context)
    required = {
        "allocation_artifact_available": True,
        "sums_to_100pct": sums_to_100pct,
        "allocation_change_recommended": allocation_change,
        "no_blocking_missing_evidence": no_missing,
        "no_existing_pending_approved_plan_conflict": no_plan_conflict,
    }
    if sums_to_100pct is not True:
        blocking.append("ALLOCATION_WEIGHTS_DO_NOT_PROVE_100PCT")
    if allocation_change is not True:
        blocking.append("ALLOCATION_CHANGE_NOT_RECOMMENDED")
    if not no_missing:
        blocking.append("MISSING_ML_OR_ATTRIBUTION_EVIDENCE")
    if not no_plan_conflict:
        blocking.append("APPROVED_PLAN_PENDING_EFFECTIVE_DATE")
    allowed = not blocking
    reason = (
        "Allocation recommendation passes eligibility gates and may become a review draft."
        if allowed
        else "Review draft generation is blocked until allocation change, 100% integrity, evidence, and plan-conflict gates pass."
    )
    warnings.extend(artifact.get("warnings") if isinstance(artifact.get("warnings"), list) else [])
    return {
        "source": SOURCE,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "latest_allocation_artifact": latest.get("artifact_path"),
        "eligibility": {
            "review_draft_generation_allowed": allowed,
            "reason": reason,
            "blocking_conditions": blocking,
            "required_conditions": required,
        },
        "rebalance_context": context,
        "warnings": warnings,
    }


def _review_rows_from_allocation(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in artifact.get("recommendations") or []:
        if not isinstance(row, dict) or not row.get("included_in_allocation_denominator"):
            continue
        proposed = row.get("proposed_weight")
        rows.append(
            {
                "strategy_uid": row.get("strategy_uid"),
                "strategy_name": row.get("display_name") or row.get("strategy_uid"),
                "canonical_status": "ACTIVE_PAPER",
                "current_weight": row.get("current_weight"),
                "recommended_weight": proposed,
                "proposed_weight": proposed,
                "evidence_status": "Allocation recommendation artifact eligible",
                "data_quality": "Backend allocation recommendation artifact",
                "ml_status": "No blocking ML evidence flag in allocation artifact",
                "recommendation_reason": row.get("reason") or "Allocation recommendation artifact eligible.",
                "action_status": row.get("allocation_action") or "REVIEW",
            }
        )
    return rows


def create_review_draft_from_allocation_recommendation(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    eligibility = build_review_draft_eligibility(root_path)
    if not eligibility.get("eligibility", {}).get("review_draft_generation_allowed"):
        return {
            "ok": False,
            "status": "BLOCKED",
            "source": SOURCE,
            "review_draft_created": False,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "eligibility": eligibility,
        }
    latest = read_latest_allocation_recommendation_artifact(root_path)
    artifact = latest.get("artifact") or {}
    snapshot = load_operational_snapshot_for_response(root_path)
    nav = _safe_number((snapshot.get("portfolio_summary") or {}).get("nav"))
    if nav is None or nav <= 0:
        return {
            "ok": False,
            "status": "BLOCKED",
            "source": SOURCE,
            "review_draft_created": False,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "eligibility": eligibility,
            "blocking_conditions": ["PORTFOLIO_NAV_UNAVAILABLE"],
        }
    draft = create_recommendation_review_draft(
        root_path,
        _review_rows_from_allocation(artifact),
        portfolio_nav=nav,
        source_recommendation_artifact=latest.get("artifact_path"),
    )
    return {
        "ok": True,
        "status": "CREATED",
        "source": SOURCE,
        "review_draft_created": True,
        "recommendation_review_draft": draft,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "eligibility": eligibility,
    }
