"""Recommendation-only review draft persistence.

This module creates user-reviewable draft artifacts from recommendation rows.
It intentionally does not apply weights, mutate ledgers, or create orders.
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


SCHEMA_VERSION = "recommendation_review_draft_v1"
REVIEW_STATUS = "DRAFT_NOT_APPLIED"
COST_RATE = 0.0005


def _path(root: Path) -> Path:
    return root / "data" / "paper_rebalance" / "recommendation_review_drafts.json"


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


def _warning_flags(row: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("data_quality", "ml_status", "evidence_status", "recommendation_reason", "action_status")
    ).upper()
    flags: list[str] = []
    if "PUBLIC_FALLBACK" in text or "PUBLIC FALLBACK" in text:
        flags.append("PUBLIC_FALLBACK")
    if "NOT_PIT" in text or "NOT PIT" in text:
        flags.append("NOT_PIT")
    if "NOT_SURVIVORSHIP" in text or "NOT SURVIVORSHIP" in text:
        flags.append("NOT_SURVIVORSHIP_FREE")
    if "MISSING_EVIDENCE" in text or "NO ML EVIDENCE" in text or "MISSING ML" in text:
        flags.append("MISSING_ML_OR_EVIDENCE_WARNING")
    if "PROTOTYPE" in text:
        flags.append("PROTOTYPE_EVIDENCE")
    return sorted(set(flags))


def _line_item(row: dict[str, Any], portfolio_nav: float) -> dict[str, Any] | None:
    if row.get("SMOKE_ONLY") or row.get("TEST_ARTIFACT") or row.get("EXCLUDE_FROM_ACTIVE_UNIVERSE"):
        raise ValueError("smoke/test rows cannot enter recommendation review draft")
    status = str(row.get("canonical_status") or row.get("status") or "").upper()
    if "PENDING" in status and "ACTIVE" not in status:
        raise ValueError("pending approval rows cannot enter recommendation review draft")
    uid = str(row.get("strategy_uid") or "").strip()
    if not uid:
        raise ValueError("missing canonical strategy_uid")
    if uid.startswith("#"):
        raise ValueError("display_label cannot be used as canonical strategy_uid")
    if any(_contains_fake(row.get(key)) for key in ("evidence_status", "data_quality", "ml_status", "recommendation_reason")):
        raise ValueError("fake evidence, ML, NAV/P&L, or data cannot enter recommendation review draft")

    current = _to_float(row.get("current_weight"))
    recommended = _to_float(row.get("recommended_weight"))
    proposed = _to_float(row.get("proposed_weight"))
    if current is None or recommended is None or proposed is None:
        raise ValueError(f"missing numeric weight for {uid}")
    if current < 0 or recommended < 0 or proposed < 0:
        raise ValueError("negative weights are not supported for recommendation review draft")

    trade = (proposed - current) * portfolio_nav
    cost = abs(proposed - current) * portfolio_nav * COST_RATE
    edited = proposed if not math.isclose(proposed, recommended, abs_tol=1e-12) else None
    return {
        "strategy_uid": uid,
        "strategy_name": row.get("strategy_name") or uid,
        "canonical_status": row.get("canonical_status") or row.get("status") or "Unavailable",
        "current_weight": current,
        "recommended_weight": recommended,
        "proposed_weight": proposed,
        "user_edited_weight": edited,
        "estimated_trade": trade,
        "estimated_transaction_cost": cost,
        "evidence_status": row.get("evidence_status") or "Missing Evidence",
        "data_quality": row.get("data_quality") or "Missing Evidence",
        "ml_status": row.get("ml_status") or "No ML evidence available",
        "recommendation_reason": row.get("recommendation_reason") or "Missing Evidence",
        "action_status": row.get("action_status") or "REVIEW",
        "review_status": REVIEW_STATUS,
        "warning_flags": _warning_flags(row),
    }


def create_recommendation_review_draft(
    root: Path,
    recommendation_rows: list[dict[str, Any]],
    *,
    portfolio_nav: float | None = None,
    source_recommendation_artifact: str | None = None,
) -> dict[str, Any]:
    if not isinstance(recommendation_rows, list) or not recommendation_rows:
        raise ValueError("recommendation_rows must be a non-empty list")
    nav = _to_float(portfolio_nav)
    if nav is None or nav <= 0:
        raise ValueError("portfolio_nav must be a positive finite number")

    line_items = [_line_item(row, nav) for row in recommendation_rows]
    total = sum(float(row["proposed_weight"]) for row in line_items)
    if total > 1.0001:
        raise ValueError("total proposed weight exceeds 100%")
    draft = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": f"recommendation-review-{uuid4().hex[:12]}",
        "created_at": _now_iso(),
        "source_recommendation_artifact": source_recommendation_artifact
        or "operational_snapshot_runtime_recommendation_rows",
        "review_status": REVIEW_STATUS,
        "status": REVIEW_STATUS,
        "line_items": line_items,
        "proposed_weight_total": total,
        "residual_cash_weight": max(0.0, 1.0 - total),
        "estimated_trade_total": sum(abs(float(row["estimated_trade"])) for row in line_items),
        "estimated_transaction_cost_total": sum(float(row["estimated_transaction_cost"]) for row in line_items),
        "recommendation_only": True,
        "draft_not_applied": True,
        "paper_only": True,
        "current_weight_mutation": False,
        "target_weight_mutation": False,
        "paper_ledger_mutation": False,
        "combined_current_mutation": False,
        "nav_pnl_impact": "NONE_UNTIL_APPROVED_AND_EFFECTIVE_DATE",
        "live_trading": False,
        "brokerage_execution": False,
    }
    store = recommendation_review_snapshot_payload(root)
    drafts = [row for row in store.get("drafts", []) if row.get("proposal_id") != draft["proposal_id"]]
    drafts.append(draft)
    _atomic_write_json(_path(root), {"schema_version": SCHEMA_VERSION, "drafts": drafts})
    return draft


def recommendation_review_snapshot_payload(root: Path) -> dict[str, Any]:
    store = _read_json(_path(root), {"schema_version": SCHEMA_VERSION, "drafts": []})
    drafts = store.get("drafts") or []
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_path": "data/paper_rebalance/recommendation_review_drafts.json",
        "drafts": drafts,
        "latest_draft": drafts[-1] if drafts else None,
        "recommendation_only": True,
        "draft_not_applied": True,
    }
