"""Unified automation control API for review-only workstation automation.

This module wraps existing automation-intelligence readers/writers.  GET-style
status construction is read-only; POST-style helpers may generate review-only
artifacts but never approve or apply paper rebalance plans.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.automation.biweekly_rebalance_proposal import (
    read_latest_biweekly_rebalance_proposal,
    write_biweekly_rebalance_proposal_artifact,
)
from src.automation.daily_allocation_recommendation import (
    read_latest_daily_allocation_recommendation,
    write_daily_allocation_recommendation_artifact,
)
from src.automation.daily_cycle import read_latest_daily_cycle_status, run_daily_automation_cycle
from src.automation.paper_allocation_proposal import (
    read_latest_paper_allocation_proposal,
    write_paper_allocation_proposal,
)


REGIME_PENDING_MESSAGE = "Regime artifact not generated yet; schema reserved for future boss/API data."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact(payload: dict[str, Any]) -> dict[str, Any]:
    artifact = payload.get("artifact")
    return artifact if isinstance(artifact, dict) else {}


def _row_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    return None


def _first_list_count(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    artifact = _artifact(payload)
    for key in keys:
        count = _row_count(artifact.get(key))
        if count is not None:
            return count
    summary = artifact.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("row_count"), int):
        return summary["row_count"]
    return None


def _latest_generated_at(payload: dict[str, Any]) -> str | None:
    artifact = _artifact(payload)
    for key in ("generated_at", "created_at", "last_run_at"):
        value = artifact.get(key) or payload.get(key)
        if value:
            return str(value)
    cycle = payload.get("daily_cycle")
    if isinstance(cycle, dict) and cycle.get("last_run_at"):
        return str(cycle["last_run_at"])
    return None


def _current_date(payload: dict[str, Any]) -> str | None:
    artifact = _artifact(payload)
    cycle = payload.get("daily_cycle")
    for source in (artifact, cycle if isinstance(cycle, dict) else {}, payload):
        for key in ("current_date", "as_of_date", "recommendation_date", "proposal_date"):
            value = source.get(key)
            if value:
                return str(value)
    generated = _latest_generated_at(payload)
    return generated[:10] if generated else None


def manual_review_schema() -> dict[str, Any]:
    return {
        "override_available": True,
        "apply_requires_user_approval": True,
        "silent_auto_apply": False,
    }


def regime_schema() -> dict[str, Any]:
    return {
        "status": "pending",
        "schema_ready": True,
        "latest_artifact_path": None,
        "current_regime": None,
        "strategy_regime_fit": [],
        "message": REGIME_PENDING_MESSAGE,
    }


def scheduler_schema(daily_cycle: dict[str, Any], *, scheduler_status: dict[str, Any] | None = None) -> dict[str, Any]:
    cycle = daily_cycle.get("daily_cycle") if isinstance(daily_cycle.get("daily_cycle"), dict) else {}
    scheduler = scheduler_status if isinstance(scheduler_status, dict) else {}
    scheduler_last_run = scheduler.get("last_successful_refresh_at") or scheduler.get("last_run_at")
    return {
        "enabled": bool(scheduler.get("enabled")),
        "external_scheduler_active": bool(scheduler.get("external_scheduler_active")),
        "cadence": scheduler.get("selected_cadence_minutes") or scheduler.get("cadence") or scheduler.get("refresh_interval_minutes"),
        "next_run_at": scheduler.get("next_scheduled_refresh_at") or scheduler.get("next_run_at"),
        "last_run_at": scheduler_last_run or cycle.get("last_run_at") or _latest_generated_at(daily_cycle),
    }


def normalize_daily_cycle(payload: dict[str, Any]) -> dict[str, Any]:
    cycle = payload.get("daily_cycle") if isinstance(payload.get("daily_cycle"), dict) else {}
    steps = cycle.get("steps") if isinstance(cycle.get("steps"), list) else []
    warnings = cycle.get("warnings") if isinstance(cycle.get("warnings"), list) else []
    errors = cycle.get("errors") if isinstance(cycle.get("errors"), list) else []
    return {
        "status": cycle.get("status") or payload.get("status") or "MISSING_ARTIFACT",
        "latest_generated_at": cycle.get("last_run_at") or _latest_generated_at(payload),
        "latest_artifact_path": payload.get("artifact_path"),
        "row_count": len(steps) if steps else 0,
        "current_date": cycle.get("as_of_date") or _current_date(payload),
        "stale": False if payload.get("ok") else True,
        "message": "; ".join(str(x) for x in (errors or warnings)) or payload.get("message"),
    }


def normalize_daily_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status") or "MISSING_ARTIFACT",
        "latest_generated_at": _latest_generated_at(payload),
        "latest_artifact_path": payload.get("artifact_path"),
        "row_count": _first_list_count(payload, ("recommendations", "rows", "allocation_rows")) or 0,
        "current_date": _current_date(payload),
    }


def normalize_rebalance_proposal(payload: dict[str, Any], *, proposal_type: str | None = None) -> dict[str, Any]:
    artifact = _artifact(payload)
    return {
        "status": payload.get("status") or "MISSING_ARTIFACT",
        "latest_generated_at": _latest_generated_at(payload),
        "latest_artifact_path": payload.get("artifact_path"),
        "row_count": _first_list_count(payload, ("proposal_rows", "rows", "allocation_rows", "recommendations")) or 0,
        "proposal_type": proposal_type or artifact.get("proposal_type") or payload.get("source"),
        "current_date": _current_date(payload),
    }


def build_automation_control_status(
    root: str | Path,
    *,
    daily_cycle_reader: Callable[[str | Path], dict[str, Any]] = read_latest_daily_cycle_status,
    daily_recommendation_reader: Callable[[str | Path], dict[str, Any]] = read_latest_daily_allocation_recommendation,
    rebalance_reader: Callable[[str | Path], dict[str, Any]] = read_latest_biweekly_rebalance_proposal,
    fallback_rebalance_reader: Callable[[str | Path], dict[str, Any]] = read_latest_paper_allocation_proposal,
    scheduler_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    daily_cycle = daily_cycle_reader(root)
    daily_recommendation = daily_recommendation_reader(root)
    rebalance = rebalance_reader(root)
    proposal_type = "biweekly_paper_rebalance_proposal_v1"
    if not rebalance.get("ok"):
        fallback = fallback_rebalance_reader(root)
        if fallback.get("ok"):
            rebalance = fallback
            proposal_type = "paper_allocation_proposal_fallback"
    normalized = {
        "ok": True,
        "status": "AVAILABLE" if all(x.get("ok") for x in (daily_cycle, daily_recommendation, rebalance)) else "PARTIAL",
        "generated_at": _now_iso(),
        "daily_cycle": normalize_daily_cycle(daily_cycle),
        "daily_recommendation": normalize_daily_recommendation(daily_recommendation),
        "rebalance_proposal": normalize_rebalance_proposal(rebalance, proposal_type=proposal_type),
        "scheduler": scheduler_schema(daily_cycle, scheduler_status=scheduler_status),
        "manual_review": manual_review_schema(),
        "regime": regime_schema(),
    }
    return normalized


def run_automation_daily_cycle_control(
    root: str | Path,
    *,
    force: bool = False,
    runner: Callable[..., dict[str, Any]] = run_daily_automation_cycle,
    daily_allocation_writer: Callable[..., dict[str, Any]] = write_daily_allocation_recommendation_artifact,
) -> dict[str, Any]:
    result = runner(root, force=force)
    recommendation_result: dict[str, Any] = {"ok": False, "status": "SKIPPED_DAILY_CYCLE_FAILED"}
    if isinstance(result, dict) and result.get("ok"):
        try:
            recommendation_result = daily_allocation_writer(root)
        except Exception as exc:
            recommendation_result = {"ok": False, "status": "FAILED", "message": f"daily_allocation_recommendation_failed: {exc}"}
    daily_cycle = normalize_daily_cycle(result if isinstance(result, dict) else {})
    daily_recommendation = normalize_daily_recommendation(recommendation_result)
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    ok = ok and bool(recommendation_result.get("ok"))
    return {
        "ok": ok,
        "status": result.get("status", daily_cycle["status"]) if ok and isinstance(result, dict) else "PARTIAL",
        "daily_cycle": daily_cycle,
        "daily_recommendation": daily_recommendation,
        "control": {
            "source": "automation_control_layer_v0",
            "review_only": True,
            "runner_status": result.get("status") if isinstance(result, dict) else "FAILED",
            "daily_allocation_recommendation_status": recommendation_result.get("status"),
        },
        "manual_review": manual_review_schema(),
        "regime": regime_schema(),
        "no_auto_apply": True,
        "approved_plan_created": False,
        "applied_event_created": False,
    }


def generate_rebalance_proposal_control(
    root: str | Path,
    *,
    force: bool = False,
    writer: Callable[..., dict[str, Any]] = write_biweekly_rebalance_proposal_artifact,
    fallback_writer: Callable[..., dict[str, Any]] = write_paper_allocation_proposal,
) -> dict[str, Any]:
    proposal_type = "biweekly_paper_rebalance_proposal_v1"
    result = writer(root)
    if not isinstance(result, dict) or not result.get("ok"):
        fallback = fallback_writer(root)
        if isinstance(fallback, dict) and fallback.get("ok"):
            result = fallback
            proposal_type = "paper_allocation_proposal_fallback"
    result = result if isinstance(result, dict) else {"ok": False, "status": "FAILED"}
    rebalance = normalize_rebalance_proposal(result, proposal_type=proposal_type)
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status") or rebalance["status"],
        "rebalance_proposal": rebalance,
        "control": {
            "source": "automation_control_layer_v0",
            "review_only": True,
            "proposal_type": proposal_type,
            "force_requested": bool(force),
        },
        "paper_only": True,
        "requires_manual_approval": True,
        "no_auto_apply": True,
        "approved_plan_created": False,
        "applied_event_created": False,
        "regime": regime_schema(),
    }
