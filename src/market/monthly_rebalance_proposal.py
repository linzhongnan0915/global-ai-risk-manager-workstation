"""Monthly paper rebalance proposal artifacts.

Proposal-only: no approvals, no paper allocation apply, no NAV/P&L or ledger
mutation, and no live/brokerage orders.
"""

from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.market.recommendation_review_draft import create_recommendation_review_draft


SCHEMA_VERSION = "monthly_rebalance_proposal_v1"
STATUS = "MONTHLY_PROPOSAL_READY"
REVIEW_STATUS = "NOT_APPROVED"
COST_RATE = 0.0005
NO_TRADE_BAND = 0.0025
PROTOTYPE_CAP = 0.03
MISSING_ML_CAP = 0.05
STARTER_CAP = 0.03


def _path(root: Path) -> Path:
    return root / "data" / "paper_rebalance" / "monthly_rebalance_proposals.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _contains_fake(value: Any) -> bool:
    return "FAKE" in str(value or "").upper() or "FABRICATED" in str(value or "").upper()


def _proposal_month(session_state: dict[str, Any] | None) -> str:
    session_state = session_state or {}
    source = (
        session_state.get("current_intraday_session")
        or session_state.get("calendar_date")
        or session_state.get("last_trading_session")
        or _now_iso()
    )
    return str(source)[:7]


def _warning_flags(row: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("data_quality", "ml_status", "evidence_status", "recommendation_reason", "action_status")
    ).upper()
    flags: set[str] = set(row.get("warning_flags") or [])
    if "PUBLIC_FALLBACK" in text or "PUBLIC FALLBACK" in text:
        flags.add("PUBLIC_FALLBACK")
    if "NOT_PIT" in text or "NOT PIT" in text:
        flags.add("NOT_PIT")
    if "NOT_SURVIVORSHIP" in text or "NOT SURVIVORSHIP" in text:
        flags.add("NOT_SURVIVORSHIP_FREE")
    if "MISSING_EVIDENCE" in text or "NO ML EVIDENCE" in text or "MISSING ML" in text:
        flags.add("MISSING_ML_OR_EVIDENCE_WARNING")
    if "PROTOTYPE" in text:
        flags.add("PROTOTYPE_EVIDENCE")
    return sorted(flags)


def _row_status_blocks(row: dict[str, Any]) -> None:
    if row.get("SMOKE_ONLY") or row.get("TEST_ARTIFACT") or row.get("EXCLUDE_FROM_ACTIVE_UNIVERSE"):
        raise ValueError("smoke/test rows cannot enter monthly rebalance proposal")
    status = str(row.get("canonical_status") or row.get("status") or "").upper()
    if "PENDING" in status and "ACTIVE" not in status:
        raise ValueError("pending approval rows cannot enter monthly rebalance proposal")
    uid = str(row.get("strategy_uid") or "").strip()
    if not uid:
        raise ValueError("missing canonical strategy_uid")
    if uid.startswith("#"):
        raise ValueError("display_label cannot be used as canonical strategy_uid")
    if any(_contains_fake(row.get(key)) for key in ("evidence_status", "data_quality", "ml_status", "recommendation_reason")):
        raise ValueError("fake evidence, ML, NAV/P&L, or data cannot enter monthly proposal")


def _cap_for(row: dict[str, Any], current: float, recommended: float) -> tuple[float, str | None]:
    flags = _warning_flags(row)
    cap: float | None = None
    reasons: list[str] = []
    status = str(row.get("canonical_status") or row.get("status") or "").upper()
    if current == 0 or "ACTIVE_UNALLOCATED" in status:
        cap = STARTER_CAP
        reasons.append("STARTER_CAP_ACTIVE_UNALLOCATED")
    if "PUBLIC_FALLBACK" in flags or "PROTOTYPE_EVIDENCE" in flags or "NOT_PIT" in flags or "NOT_SURVIVORSHIP_FREE" in flags:
        cap = min(cap if cap is not None else PROTOTYPE_CAP, PROTOTYPE_CAP)
        reasons.append("PROTOTYPE_PUBLIC_DATA_CAP")
    if "MISSING_ML_OR_EVIDENCE_WARNING" in flags:
        cap = min(cap if cap is not None else MISSING_ML_CAP, MISSING_ML_CAP)
        reasons.append("MISSING_ML_CAP")
    proposed = recommended if cap is None else min(recommended, cap)
    return proposed, " / ".join(sorted(set(reasons))) if reasons else None


def _proposal_row(row: dict[str, Any], *, portfolio_nav: float) -> dict[str, Any]:
    _row_status_blocks(row)
    current = _to_float(row.get("current_weight"))
    recommended = _to_float(row.get("recommended_weight", row.get("proposed_weight")))
    if current is None or recommended is None:
        raise ValueError("monthly proposal rows require numeric current_weight and recommended_weight")
    if current < 0 or recommended < 0:
        raise ValueError("negative weights are not supported for monthly proposal")
    proposed, cap_reason = _cap_for(row, current, recommended)
    action = row.get("action_status") or "REVIEW"
    monthly_reason = "Monthly proposal follows recommendation."
    if abs(proposed - current) < NO_TRADE_BAND:
        proposed = current
        action = "HOLD"
        monthly_reason = "No-trade band retained current weight."
    elif cap_reason:
        monthly_reason = f"Recommendation capped: {cap_reason}."
    trade = (proposed - current) * portfolio_nav
    cost = abs(proposed - current) * portfolio_nav * COST_RATE
    return {
        "strategy_uid": str(row.get("strategy_uid")),
        "strategy_name": row.get("strategy_name") or row.get("strategy_uid"),
        "status": row.get("canonical_status") or row.get("status") or "Unavailable",
        "current_weight": current,
        "recommended_weight": recommended,
        "monthly_proposed_weight": proposed,
        "proposed_weight": proposed,
        "estimated_trade": trade,
        "estimated_transaction_cost": cost,
        "recommendation_reason": row.get("recommendation_reason") or "Missing Evidence",
        "monthly_proposal_reason": monthly_reason,
        "evidence_status": row.get("evidence_status") or "Missing Evidence",
        "data_quality": row.get("data_quality") or "Missing Evidence",
        "ml_status": row.get("ml_status") or "No ML evidence available",
        "action_status": action,
        "cap_reason": cap_reason,
        "warning_flags": _warning_flags(row),
        "lineage_references": row.get("lineage_references") or row.get("lineage") or {
            "source": "daily_recommendation_row",
        },
    }


def monthly_rebalance_proposal_snapshot_payload(root: Path) -> dict[str, Any]:
    store = _read_json(_path(root), {"schema_version": SCHEMA_VERSION, "proposals": []})
    proposals = store.get("proposals") or []
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_path": "data/paper_rebalance/monthly_rebalance_proposals.json",
        "proposals": proposals,
        "latest_proposal": proposals[-1] if proposals else None,
        "proposal_only": True,
    }


def create_monthly_rebalance_proposal(
    root: Path,
    recommendation_rows: list[dict[str, Any]],
    *,
    portfolio_nav: float | None,
    session_state: dict[str, Any] | None,
    source_recommendation_artifact: str | None = None,
    source_strategy_universe_snapshot: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not isinstance(recommendation_rows, list) or not recommendation_rows:
        raise ValueError("recommendation_rows must be a non-empty list")
    nav = _to_float(portfolio_nav)
    if nav is None or nav <= 0:
        raise ValueError("portfolio_nav must be a positive finite number")
    month = _proposal_month(session_state)
    store = monthly_rebalance_proposal_snapshot_payload(root)
    existing = [
        proposal for proposal in store.get("proposals") or []
        if proposal.get("proposal_month") == month
    ]
    if existing and not force:
        return existing[-1]
    rows = [_proposal_row(row, portfolio_nav=nav) for row in recommendation_rows]
    total = sum(float(row["monthly_proposed_weight"]) for row in rows)
    if total > 1.0001:
        scale = 1.0 / total
        for row in rows:
            row["monthly_proposed_weight"] *= scale
            row["proposed_weight"] = row["monthly_proposed_weight"]
            row["estimated_trade"] = (row["proposed_weight"] - row["current_weight"]) * nav
            row["estimated_transaction_cost"] = abs(row["proposed_weight"] - row["current_weight"]) * nav * COST_RATE
            row["cap_reason"] = (row.get("cap_reason") or "NORMALIZED_TO_100_PERCENT")
            row["monthly_proposal_reason"] = f"{row['monthly_proposal_reason']} Normalized to 100% total."
        total = 1.0
    proposal = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": f"monthly-proposal-{uuid4().hex[:12]}",
        "created_at": _now_iso(),
        "proposal_month": month,
        "session_state": deepcopy(session_state or {}),
        "source_recommendation_artifact": source_recommendation_artifact or "operational_snapshot_runtime_recommendation_rows",
        "source_strategy_universe_snapshot": source_strategy_universe_snapshot,
        "status": STATUS,
        "review_status": REVIEW_STATUS,
        "portfolio_nav_used_for_cost_estimate": nav,
        "total_current_weight": sum(float(row["current_weight"]) for row in rows),
        "total_proposed_weight": total,
        "residual_cash": max(0.0, 1.0 - total),
        "estimated_total_trade_abs": sum(abs(float(row["estimated_trade"])) for row in rows),
        "estimated_total_transaction_cost": sum(float(row["estimated_transaction_cost"]) for row in rows),
        "warnings": sorted({flag for row in rows for flag in row.get("warning_flags", [])}),
        "no_live_orders": True,
        "no_brokerage_orders": True,
        "proposal_only": True,
        "current_weight_mutation": False,
        "target_weight_mutation": False,
        "paper_ledger_mutation": False,
        "combined_current_mutation": False,
        "nav_pnl_impact": "NONE_PROPOSAL_ONLY",
        "rows": rows,
    }
    proposals = [proposal for proposal in store.get("proposals", []) if not (force and proposal.get("proposal_month") == month)]
    proposals.append(proposal)
    _atomic_write_json(_path(root), {"schema_version": SCHEMA_VERSION, "proposals": proposals})
    return proposal


def create_review_draft_from_monthly_proposal(root: Path, proposal_id: str | None = None) -> dict[str, Any]:
    payload = monthly_rebalance_proposal_snapshot_payload(root)
    proposals = payload.get("proposals") or []
    proposal = None
    if proposal_id:
        proposal = next((row for row in proposals if row.get("proposal_id") == proposal_id), None)
        if proposal is None:
            raise ValueError("monthly proposal not found")
    else:
        proposal = payload.get("latest_proposal")
    if not proposal:
        raise ValueError("no monthly proposal available")
    draft = create_recommendation_review_draft(
        root,
        proposal.get("rows") or [],
        portfolio_nav=proposal.get("portfolio_nav_used_for_cost_estimate") or 1.0,
        source_recommendation_artifact=f"monthly_rebalance_proposal:{proposal['proposal_id']}",
    )
    return draft
