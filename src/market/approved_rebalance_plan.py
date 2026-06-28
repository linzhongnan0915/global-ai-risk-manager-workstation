"""Approved rebalance plan artifacts waiting for an effective date.

Phase 2A approval only: this module writes approval artifacts and never applies
weights, mutates ledgers, books NAV/P&L, or creates orders.
"""

from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.market.recommendation_review_draft import recommendation_review_snapshot_payload


SCHEMA_VERSION = "approved_rebalance_plan_v1"
APPROVED_STATUS = "APPROVED_WAITING_EFFECTIVE_DATE"
APPLIED_STATUS = "APPLIED_PAPER"
EFFECTIVE_DATE_RULE = "NEXT_TRADING_SESSION_FROM_BACKEND_SESSION_STATE"
COST_RATE = 0.0005
APPLY_LOCK_TTL_SECONDS = 120
APPLY_LOCK_WAIT_SECONDS = 30
APPLY_LOCK_POLL_SECONDS = 0.05


def _path(root: Path) -> Path:
    return root / "data" / "paper_rebalance" / "approved_rebalance_plans.json"


def _events_path(root: Path) -> Path:
    return root / "data" / "paper_rebalance" / "applied_rebalance_events.json"


def _target_path(root: Path) -> Path:
    return root / "data" / "paper_rebalance" / "current_paper_target_weights.json"


def _apply_lock_path(root: Path) -> Path:
    return root / "data" / "paper_rebalance" / "approved_rebalance_apply.lock"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _lock_is_stale(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime > APPLY_LOCK_TTL_SECONDS
    except OSError:
        return False


@contextmanager
def _approved_apply_lock(root: Path):
    path = _apply_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + APPLY_LOCK_WAIT_SECONDS
    acquired = False
    while not acquired:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {
                "pid": os.getpid(),
                "acquired_at": _now_iso(),
                "acquired_monotonic": time.monotonic(),
                "lock_scope": "approved_rebalance_plan_apply",
            }
            os.write(fd, json.dumps(payload, ensure_ascii=True).encode("utf-8"))
            os.close(fd)
            acquired = True
        except (FileExistsError, PermissionError):
            if _lock_is_stale(path):
                try:
                    path.unlink()
                    continue
                except (FileNotFoundError, PermissionError):
                    continue
            if time.monotonic() >= deadline:
                raise TimeoutError("approved rebalance apply lock is busy")
            time.sleep(APPLY_LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        if acquired:
            for _ in range(100):
                try:
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(APPLY_LOCK_POLL_SECONDS)


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


def _strategy_uid(row: dict[str, Any]) -> str | None:
    value = row.get("strategy_uid") or row.get("strategy_id") or row.get("internal_id") or row.get("id")
    return str(value) if value else None


def _is_combined(row: dict[str, Any]) -> bool:
    return (
        row.get("internal_id") == "COMBINED_PORTFOLIO"
        or row.get("strategy_uid") == "COMBINED_PORTFOLIO"
        or row.get("display_id") == "#COMBINED"
        or "COMBINED" in str(row.get("strategy_name") or row.get("display_name") or "").upper()
    )


def _warning_flags(row: dict[str, Any]) -> list[str]:
    flags = set(row.get("warning_flags") or [])
    text = " ".join(
        str(row.get(key) or "")
        for key in ("data_quality", "ml_status", "evidence_status", "recommendation_reason", "action_status")
    ).upper()
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


def _draft_by_id(root: Path, draft_id: str | None) -> dict[str, Any]:
    payload = recommendation_review_snapshot_payload(root)
    drafts = payload.get("drafts") or []
    if draft_id:
        for draft in drafts:
            if draft.get("proposal_id") == draft_id:
                return draft
        raise ValueError("recommendation review draft not found")
    latest = payload.get("latest_draft")
    if not latest:
        raise ValueError("no recommendation review draft available for approval")
    return latest


def _approved_row(row: dict[str, Any], *, portfolio_nav: float) -> dict[str, Any]:
    if row.get("SMOKE_ONLY") or row.get("TEST_ARTIFACT") or row.get("EXCLUDE_FROM_ACTIVE_UNIVERSE"):
        raise ValueError("smoke/test rows cannot enter approved rebalance plan")
    status = str(row.get("canonical_status") or row.get("status") or "").upper()
    if "PENDING" in status and "ACTIVE" not in status:
        raise ValueError("pending approval rows cannot enter approved rebalance plan")
    uid = str(row.get("strategy_uid") or "").strip()
    if not uid:
        raise ValueError("missing canonical strategy_uid")
    if uid.startswith("#"):
        raise ValueError("display_label cannot be used as canonical strategy_uid")
    if any(_contains_fake(row.get(key)) for key in ("evidence_status", "data_quality", "ml_status", "recommendation_reason")):
        raise ValueError("fake evidence, ML, NAV/P&L, or data cannot enter approved rebalance plan")

    current = _to_float(row.get("current_weight"))
    recommended = _to_float(row.get("recommended_weight"))
    proposed = _to_float(row.get("proposed_weight"))
    approved = _to_float(row.get("approved_target_weight", proposed))
    if current is None or recommended is None or proposed is None or approved is None:
        raise ValueError(f"missing numeric weight for {uid}")
    if current < 0 or recommended < 0 or proposed < 0 or approved < 0:
        raise ValueError("negative weights are not supported for approved rebalance plan")

    trade = (approved - current) * portfolio_nav
    cost = abs(approved - current) * portfolio_nav * COST_RATE
    return {
        "strategy_uid": uid,
        "strategy_name": row.get("strategy_name") or uid,
        "current_weight": current,
        "recommended_weight": recommended,
        "proposed_weight": proposed,
        "approved_target_weight": approved,
        "user_edited_weight": row.get("user_edited_weight"),
        "estimated_trade": trade,
        "estimated_transaction_cost": cost,
        "evidence_status": row.get("evidence_status") or "Missing Evidence",
        "data_quality": row.get("data_quality") or "Missing Evidence",
        "ml_status": row.get("ml_status") or "No ML evidence available",
        "recommendation_reason": row.get("recommendation_reason") or "Missing Evidence",
        "action_status": row.get("action_status") or "REVIEW",
        "warning_flags": _warning_flags(row),
        "lineage_references": row.get("lineage_references") or row.get("lineage") or {
            "source": "recommendation_review_draft_line_item",
        },
    }


def _plan_store(root: Path) -> dict[str, Any]:
    return _read_json(_path(root), {"schema_version": SCHEMA_VERSION, "plans": []})


def _write_plan_store(root: Path, plans: list[dict[str, Any]]) -> None:
    _atomic_write_json(_path(root), {"schema_version": SCHEMA_VERSION, "plans": plans})


def _event_store(root: Path) -> dict[str, Any]:
    return _read_json(_events_path(root), {"schema_version": "applied_rebalance_events_v1", "events": []})


def _write_event_store(root: Path, events: list[dict[str, Any]]) -> None:
    _atomic_write_json(_events_path(root), {"schema_version": "applied_rebalance_events_v1", "events": events})


def _plan_apply_key(plan: dict[str, Any]) -> str:
    plan_id = str(plan.get("plan_id") or "").strip()
    if plan_id:
        return f"approved_rebalance_plan:{plan_id}"
    material = {
        "approved_at": plan.get("approved_at"),
        "effective_date": plan.get("effective_date"),
        "effective_date_rule": plan.get("effective_date_rule"),
        "source_draft_id": plan.get("source_draft_id"),
        "status": plan.get("status"),
        "rows": [
            {
                "strategy_uid": row.get("strategy_uid"),
                "approved_target_weight": row.get("approved_target_weight"),
                "lineage_references": row.get("lineage_references"),
            }
            for row in sorted(plan.get("rows") or [], key=lambda item: str(item.get("strategy_uid") or ""))
        ],
    }
    digest = sha256(json.dumps(material, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()
    return f"approved_rebalance_plan_hash:{digest}"


def _event_matches_apply_key(event: dict[str, Any], *, apply_key: str, plan_id: str | None) -> bool:
    if event.get("apply_key") == apply_key:
        return True
    return bool(plan_id and event.get("plan_id") == plan_id)


def _event_for_apply_key(events: list[dict[str, Any]], *, apply_key: str, plan_id: str | None) -> dict[str, Any] | None:
    for event in reversed(events):
        if _event_matches_apply_key(event, apply_key=apply_key, plan_id=plan_id):
            return event
    return None


def _dedupe_events_for_write(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        key = event.get("apply_key") or (f"approved_rebalance_plan:{event.get('plan_id')}" if event.get("plan_id") else None)
        if key:
            if key in seen:
                continue
            seen.add(key)
        deduped.append(event)
    return deduped


def _active_strategy_by_uid(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("strategies") or []:
        uid = _strategy_uid(row)
        if not uid:
            continue
        if row.get("SMOKE_ONLY") or row.get("TEST_ARTIFACT") or row.get("EXCLUDE_FROM_ACTIVE_UNIVERSE"):
            continue
        status = str(row.get("current_operational_status") or row.get("status") or "").upper()
        membership = str(row.get("membership_state") or "").lower()
        if "PENDING" in status or membership in {"approved_pending", "pending"}:
            continue
        if membership and membership != "executed":
            continue
        active[uid] = row
    return active


def _current_weight_for_uid(root: Path, snapshot: dict[str, Any], uid: str) -> float:
    current_target = _read_json(_target_path(root), None)
    weights = (current_target or {}).get("weights") or {}
    if uid in weights and _to_float(weights[uid]) is not None:
        return float(weights[uid])
    row = _active_strategy_by_uid(snapshot).get(uid) or {}
    return _to_float(row.get("current_weight", row.get("sleeve_weight"))) or 0.0


def _session_has_reached_effective_date(session_state: dict[str, Any], effective_date: str | None) -> bool:
    if not effective_date:
        return False
    markers = [
        session_state.get("current_intraday_session"),
        session_state.get("last_trading_session"),
        session_state.get("calendar_date"),
    ]
    reached = [str(marker)[:10] for marker in markers if marker]
    return bool(reached and max(reached) >= str(effective_date)[:10])


def _load_plan(root: Path, plan_id: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    store = _plan_store(root)
    plans = store.get("plans") or []
    if plan_id:
        for plan in plans:
            if plan.get("plan_id") == plan_id:
                return plan, plans
        raise ValueError("approved rebalance plan not found")
    eligible = [
        plan for plan in plans
        if plan.get("status") in {APPROVED_STATUS, APPLIED_STATUS}
    ]
    if not eligible:
        raise ValueError("no approved rebalance plan available")
    return eligible[-1], plans


def _event_for_plan(root: Path, plan_id: str) -> dict[str, Any] | None:
    for event in reversed(_event_store(root).get("events") or []):
        if event.get("plan_id") == plan_id:
            return event
    return None


def apply_approved_rebalance_plan(
    root: Path,
    *,
    snapshot: dict[str, Any],
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Apply an approved paper plan once the backend session_state reaches its effective date."""
    with _approved_apply_lock(root):
        plan, plans = _load_plan(root, plan_id)
        apply_key = _plan_apply_key(plan)
        plan_id_value = str(plan.get("plan_id") or "") or None
        event_store = _event_store(root)
        events = event_store.get("events") or []
        existing_event = _event_for_apply_key(events, apply_key=apply_key, plan_id=plan_id_value)
        if existing_event or plan.get("status") == APPLIED_STATUS:
            current_target = _read_json(_target_path(root), None)
            return {
                "applied": False,
                "already_applied": True,
                "plan": plan,
                "event": existing_event,
                "current_paper_target": current_target,
                "apply_key": apply_key,
                "message": "approved rebalance plan already applied; no additional cost booked",
            }
        if plan.get("status") != APPROVED_STATUS:
            raise ValueError("approved rebalance plan must be APPROVED_WAITING_EFFECTIVE_DATE before apply")

        session_state = snapshot.get("session_state") or {}
        if not _session_has_reached_effective_date(session_state, plan.get("effective_date")):
            return {
                "applied": False,
                "already_applied": False,
                "plan": plan,
                "event": None,
                "apply_key": apply_key,
                "message": "effective date has not arrived",
            }

        active = _active_strategy_by_uid(snapshot)
        portfolio_nav = _to_float(plan.get("portfolio_nav_used_for_cost_estimate")) or _to_float((snapshot.get("portfolio_summary") or {}).get("nav"))
        if portfolio_nav is None or portfolio_nav <= 0:
            raise ValueError("valid portfolio NAV is required for paper rebalance apply")

        previous_weights: dict[str, float] = {}
        new_weights: dict[str, float] = {}
        trade_weight: dict[str, float] = {}
        cost_by_strategy: dict[str, float] = {}
        for row in plan.get("rows") or []:
            uid = str(row.get("strategy_uid") or "").strip()
            if not uid:
                raise ValueError("missing canonical strategy_uid")
            if uid.startswith("#"):
                raise ValueError("display_label cannot be used as canonical strategy_uid")
            if row.get("SMOKE_ONLY") or row.get("TEST_ARTIFACT") or row.get("EXCLUDE_FROM_ACTIVE_UNIVERSE"):
                raise ValueError("smoke/test rows cannot apply")
            if uid not in active:
                raise ValueError(f"approved row is not an active paper strategy: {uid}")
            target = _to_float(row.get("approved_target_weight"))
            if target is None or target < 0:
                raise ValueError("approved target weights must be finite non-negative numbers")
            prior = _current_weight_for_uid(root, snapshot, uid)
            previous_weights[uid] = prior
            new_weights[uid] = target
            trade_weight[uid] = target - prior
            cost_by_strategy[uid] = abs(target - prior) * portfolio_nav * COST_RATE
        target_total = sum(new_weights.values())
        if target_total > 1.0001:
            raise ValueError("applied paper target total exceeds 100%")

        ordinary_weights = {
            uid: weight
            for uid, weight in new_weights.items()
            if not _is_combined(active.get(uid, {}))
        }
        combined_summary = {
            "ordinary_strategy_count": len(ordinary_weights),
            "ordinary_weight_total": sum(ordinary_weights.values()),
            "computed_from": "active ordinary strategy_uid weights",
        }
        total_cost = sum(cost_by_strategy.values())
        applied_at = _now_iso()
        event_id = f"applied-rebalance-{sha256(apply_key.encode('utf-8')).hexdigest()[:12]}"
        event = {
            "schema_version": "applied_rebalance_event_v1",
            "event_id": event_id,
            "apply_key": apply_key,
            "plan_id": plan.get("plan_id"),
            "applied_at": applied_at,
            "applied_effective_date": plan.get("effective_date"),
            "previous_weights_by_strategy_uid": previous_weights,
            "new_weights_by_strategy_uid": new_weights,
            "per_strategy_trade_weight": trade_weight,
            "per_strategy_transaction_cost": cost_by_strategy,
            "total_transaction_cost": total_cost,
            "portfolio_nav_used_for_cost_estimate": portfolio_nav,
            "combined_dynamic_summary": combined_summary,
            "no_live_orders": True,
            "no_brokerage_orders": True,
            "paper_only": True,
            "old_historical_pnl_rewritten": False,
        }
        target_payload = {
            "schema_version": SCHEMA_VERSION,
            "source_label": "approved_rebalance_plan",
            "apply_key": apply_key,
            "applied_plan_id": plan.get("plan_id"),
            "applied_event_id": event["event_id"],
            "applied_at": applied_at,
            "intended_effective_date": plan.get("effective_date"),
            "applied_effective_date": plan.get("effective_date"),
            "applied_status": APPLIED_STATUS,
            "weights": new_weights,
            "previous_weights": previous_weights,
            "target_total": target_total,
            "residual_cash_weight": max(0.0, 1.0 - target_total),
            "paper_transaction_cost_total": total_cost,
            "paper_trade_weight_by_strategy_uid": trade_weight,
            "cost_by_strategy": cost_by_strategy,
            "combined_dynamic_summary": combined_summary,
            "execution_mode": "Paper Only",
            "live_brokerage_fill": "No",
            "official_ledger_mutation": "No",
            "paper_only": True,
            "no_live_orders": True,
            "no_brokerage_orders": True,
        }
        updated_plan = deepcopy(plan)
        updated_plan.update(
            {
                "status": APPLIED_STATUS,
                "applied_status": APPLIED_STATUS,
                "apply_key": apply_key,
                "applied_at": applied_at,
                "applied_effective_date": plan.get("effective_date"),
                "applied_event_id": event["event_id"],
                "total_transaction_cost_booked": total_cost,
                "old_historical_pnl_rewritten": False,
                "live_orders_created": False,
                "brokerage_orders_created": False,
            }
        )
        _atomic_write_json(_target_path(root), target_payload)
        _write_event_store(root, _dedupe_events_for_write([*events, event]))
        _write_plan_store(root, [updated_plan if row.get("plan_id") == plan.get("plan_id") else row for row in plans])
        return {
            "applied": True,
            "already_applied": False,
            "plan": updated_plan,
            "event": event,
            "current_paper_target": target_payload,
            "apply_key": apply_key,
        }


def apply_due_approved_rebalance_plan(
    root: Path,
    *,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Apply the latest approved paper plan only when backend session_state allows it."""
    try:
        plan, _plans = _load_plan(root)
    except ValueError:
        return {
            "attempted": False,
            "applied": False,
            "already_applied": False,
            "status": "NOT_AVAILABLE",
            "message": "no approved rebalance plan available",
        }
    try:
        result = apply_approved_rebalance_plan(root, snapshot=snapshot, plan_id=plan.get("plan_id"))
    except TimeoutError as exc:
        status = paper_rebalance_automation_status(root, snapshot=snapshot)
        return {
            "attempted": True,
            "applied": False,
            "already_applied": bool(status.get("already_applied")),
            "skipped": not bool(status.get("already_applied")),
            "status": status.get("status") or "LOCK_BUSY",
            "plan_id": plan.get("plan_id"),
            "apply_key": status.get("apply_key") or _plan_apply_key(plan),
            "event_id": status.get("event_id"),
            "effective_date": plan.get("effective_date"),
            "message": "approved rebalance apply lock busy; no duplicate apply attempted" if not status.get("already_applied") else status.get("message"),
            "lock_error": str(exc),
        }
    except Exception as exc:
        return {
            "attempted": True,
            "applied": False,
            "already_applied": False,
            "status": "REVIEW_REQUIRED",
            "plan_id": plan.get("plan_id"),
            "message": str(exc),
        }
    return {
        "attempted": True,
        "applied": bool(result.get("applied")),
        "already_applied": bool(result.get("already_applied")),
        "status": (result.get("plan") or {}).get("status") or plan.get("status"),
        "plan_id": (result.get("plan") or plan).get("plan_id"),
        "apply_key": result.get("apply_key") or (result.get("event") or {}).get("apply_key"),
        "event_id": (result.get("event") or {}).get("event_id"),
        "effective_date": (result.get("plan") or plan).get("effective_date"),
        "message": result.get("message") or (
            "approved rebalance plan applied"
            if result.get("applied")
            else "approved rebalance automation checked; no apply performed"
        ),
    }


def paper_rebalance_automation_status(root: Path, *, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Read-only paper rebalance automation status for dashboard snapshots."""
    try:
        plan, _plans = _load_plan(root)
    except ValueError:
        return {
            "attempted": False,
            "applied": False,
            "already_applied": False,
            "status": "NOT_AVAILABLE",
            "message": "no approved rebalance plan available",
            "mutation_allowed_from_snapshot": False,
        }
    apply_key = _plan_apply_key(plan)
    plan_id = str(plan.get("plan_id") or "") or None
    events = _event_store(root).get("events") or []
    event = _event_for_apply_key(events, apply_key=apply_key, plan_id=plan_id)
    reached = _session_has_reached_effective_date(snapshot.get("session_state") or {}, plan.get("effective_date"))
    if event or plan.get("status") == APPLIED_STATUS:
        status = APPLIED_STATUS
        message = "approved rebalance plan already applied"
        already_applied = True
    elif reached and plan.get("status") == APPROVED_STATUS:
        status = "DUE_NOT_APPLIED"
        message = "effective date reached; explicit automation service must apply"
        already_applied = False
    elif plan.get("status") == APPROVED_STATUS:
        status = APPROVED_STATUS
        message = "effective date has not arrived"
        already_applied = False
    else:
        status = "REVIEW_REQUIRED"
        message = "approved rebalance plan status is not eligible for automation"
        already_applied = False
    return {
        "attempted": False,
        "applied": False,
        "already_applied": already_applied,
        "status": status,
        "plan_id": plan.get("plan_id"),
        "apply_key": apply_key,
        "event_id": (event or {}).get("event_id"),
        "effective_date": plan.get("effective_date"),
        "effective_date_reached": reached,
        "applied_event_exists": bool(event),
        "mutation_allowed_from_snapshot": False,
        "message": message,
    }


def create_approved_rebalance_plan(
    root: Path,
    *,
    snapshot: dict[str, Any],
    draft_id: str | None = None,
) -> dict[str, Any]:
    draft = _draft_by_id(root, draft_id)
    session_state = snapshot.get("session_state") or {}
    effective_date = session_state.get("next_trading_session")
    if not effective_date:
        raise ValueError("backend session_state.next_trading_session is required for approval")

    portfolio_nav = _to_float((snapshot.get("portfolio_summary") or {}).get("nav"))
    if portfolio_nav is None or portfolio_nav <= 0:
        raise ValueError("valid portfolio NAV is required for cost estimate")
    rows = [
        _approved_row(row, portfolio_nav=portfolio_nav)
        for row in draft.get("line_items") or []
    ]
    if not rows:
        raise ValueError("approved rebalance plan requires at least one draft row")
    total_target = sum(float(row["approved_target_weight"]) for row in rows)
    if total_target > 1.0001:
        raise ValueError("total approved target weight exceeds 100%")

    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": f"approved-rebalance-{uuid4().hex[:12]}",
        "source_draft_id": draft.get("proposal_id"),
        "source_recommendation_artifact": draft.get("source_recommendation_artifact"),
        "approved_at": _now_iso(),
        "approved_by": "USER_UI",
        "approval_channel": "dashboard",
        "status": APPROVED_STATUS,
        "effective_date": effective_date,
        "effective_date_rule": EFFECTIVE_DATE_RULE,
        "calendar_date": session_state.get("calendar_date"),
        "last_trading_session": session_state.get("last_trading_session"),
        "next_trading_session": session_state.get("next_trading_session"),
        "market_session_status": session_state.get("market_session_status"),
        "portfolio_nav_used_for_cost_estimate": portfolio_nav,
        "total_current_weight": sum(float(row["current_weight"]) for row in rows),
        "total_approved_target_weight": total_target,
        "residual_cash": max(0.0, 1.0 - total_target),
        "estimated_total_trade_abs": sum(abs(float(row["estimated_trade"])) for row in rows),
        "estimated_total_transaction_cost": sum(float(row["estimated_transaction_cost"]) for row in rows),
        "rows": rows,
        "warnings": sorted({flag for row in rows for flag in row.get("warning_flags", [])}),
        "approval_only": True,
        "waiting_effective_date": True,
        "current_weight_mutation": False,
        "target_weight_mutation": False,
        "paper_ledger_mutation": False,
        "combined_current_mutation": False,
        "nav_pnl_impact": "NONE_UNTIL_EFFECTIVE_DATE_APPLY",
        "live_orders_created": False,
        "brokerage_orders_created": False,
        "live_trading": False,
        "brokerage_execution": False,
    }
    store = approved_rebalance_plan_snapshot_payload(root)
    plans = [row for row in store.get("plans", []) if row.get("plan_id") != plan["plan_id"]]
    plans.append(plan)
    _atomic_write_json(_path(root), {"schema_version": SCHEMA_VERSION, "plans": plans})
    return plan


def approved_rebalance_plan_snapshot_payload(root: Path) -> dict[str, Any]:
    store = _read_json(_path(root), {"schema_version": SCHEMA_VERSION, "plans": []})
    event_store = _event_store(root)
    plans = store.get("plans") or []
    events = event_store.get("events") or []
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_path": "data/paper_rebalance/approved_rebalance_plans.json",
        "applied_event_artifact_path": "data/paper_rebalance/applied_rebalance_events.json",
        "plans": plans,
        "applied_events": events,
        "latest_plan": plans[-1] if plans else None,
        "latest_applied_event": events[-1] if events else None,
        "approval_only": True,
        "apply_enabled": True,
    }
