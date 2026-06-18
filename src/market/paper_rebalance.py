"""Paper-only target allocation and rebalance plan persistence."""

from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "paper_rebalance_v1"
SOURCE_LABEL = "user_adjusted_paper_target"
COST_ASSUMPTION = "5 bps buy / 5 bps sell"
EXECUTION_MODE = "Paper Only"
LIVE_BROKERAGE_FILL = "No"
OFFICIAL_LEDGER_MUTATION = "No"
DUST_NOTIONAL = 100.0
DUST_DRIFT = 0.0001


def _paths(root: Path) -> dict[str, Path]:
    base = root / "data" / "paper_rebalance"
    return {
        "target": base / "current_paper_target_weights.json",
        "plans": base / "paper_rebalance_plans.json",
        "costs": base / "paper_rebalance_costs.json",
    }


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


def _strategy_id(row: dict[str, Any]) -> str | None:
    value = row.get("internal_id") or row.get("strategy_id") or row.get("id")
    return str(value) if value else None


def active_paper_sleeves(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    removed = set(snapshot.get("removed_from_current_workstation_strategy_ids") or [])
    rows = []
    for row in snapshot.get("strategies") or []:
        strategy_id = _strategy_id(row)
        if not strategy_id or strategy_id in removed:
            continue
        if row.get("membership_state") != "executed":
            continue
        rows.append(row)
    return rows


def next_business_day(value: str | None) -> str:
    try:
        current = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        current = datetime.now(timezone.utc).date()
    current += timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current.isoformat()


def _as_of_date(snapshot: dict[str, Any]) -> str | None:
    return (snapshot.get("portfolio_summary") or {}).get("as_of_date") or snapshot.get("latest_official_ledger_date")


def _plan_store(root: Path) -> dict[str, Any]:
    return _read_json(_paths(root)["plans"], {"schema_version": SCHEMA_VERSION, "plans": []})


def _cost_store(root: Path) -> dict[str, Any]:
    return _read_json(_paths(root)["costs"], {"schema_version": SCHEMA_VERSION, "costs": []})


def _current_target(root: Path) -> dict[str, Any] | None:
    payload = _read_json(_paths(root)["target"], None)
    if not isinstance(payload, dict):
        return None
    return payload


def _persist_plan(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    store = _plan_store(root)
    plans = [row for row in store.get("plans", []) if row.get("plan_id") != plan.get("plan_id")]
    plans.append(plan)
    store = {"schema_version": SCHEMA_VERSION, "plans": plans}
    _atomic_write_json(_paths(root)["plans"], store)
    return plan


def _load_plan(root: Path, plan_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    store = _plan_store(root)
    plans = store.get("plans") or []
    for plan in plans:
        if plan.get("plan_id") == plan_id:
            return plan, plans
    raise ValueError("paper rebalance plan not found")


def _write_plans(root: Path, plans: list[dict[str, Any]]) -> None:
    _atomic_write_json(_paths(root)["plans"], {"schema_version": SCHEMA_VERSION, "plans": plans})


def _target_total(target_weights: dict[str, Any]) -> float:
    total = 0.0
    for value in target_weights.values():
        number = _to_float(value)
        if number is None or number < 0:
            raise ValueError("target weights must be finite non-negative numbers")
        total += number
    return total


def _applied_weights(root: Path) -> dict[str, float]:
    current = _current_target(root) or {}
    weights = current.get("weights") or {}
    return {
        str(strategy_id): float(weight)
        for strategy_id, weight in weights.items()
        if _to_float(weight) is not None
    }


def _current_weight(root: Path, row: dict[str, Any]) -> float | None:
    strategy_id = _strategy_id(row)
    applied = _applied_weights(root)
    if strategy_id in applied:
        return applied[strategy_id]
    return _to_float(row.get("current_weight", row.get("sleeve_weight")))


def _line_action_and_reason(
    *,
    current_weight: float | None,
    target_weight: float | None,
    trade_notional: float | None,
    drift: float | None,
) -> tuple[str, str]:
    if current_weight is None or target_weight is None or trade_notional is None or drift is None:
        return "REVIEW", "Data incomplete / review required"
    if abs(trade_notional) < DUST_NOTIONAL or abs(drift) < DUST_DRIFT:
        if abs(drift) < DUST_DRIFT:
            return "HOLD", "Equal-weight maintained"
        return "HOLD", "Dust trade ignored"
    if drift > 0:
        return "INCREASE", "Increase toward target"
    if drift < 0:
        return "REDUCE", "Reduce overweight sleeve"
    return "HOLD", "Equal-weight maintained"


def generate_paper_rebalance_plan(
    root: Path,
    snapshot: dict[str, Any],
    target_weights: dict[str, Any],
    *,
    intended_effective_date: str | None = None,
) -> dict[str, Any]:
    if not isinstance(target_weights, dict):
        raise ValueError("target_weights must be an object")
    sleeves = active_paper_sleeves(snapshot)
    if not sleeves:
        raise ValueError("no active paper sleeves available")
    active_ids = {_strategy_id(row) for row in sleeves}
    unknown = sorted(set(map(str, target_weights)) - {x for x in active_ids if x})
    if unknown:
        raise ValueError(f"target_weights includes inactive or unknown sleeves: {', '.join(unknown)}")
    total = _target_total(target_weights)
    if total > 1.0001:
        raise ValueError("target total exceeds 100%; normalize before generating a paper plan")

    capital = _to_float((snapshot.get("portfolio_summary") or {}).get("nav"))
    if capital is None:
        capital = _to_float((snapshot.get("capital_reconciliation") or {}).get("initial_shadow_capital"))
    if capital is None:
        capital = 1_000_000.0

    line_items: list[dict[str, Any]] = []
    for row in sleeves:
        strategy_id = _strategy_id(row)
        target = _to_float(target_weights.get(strategy_id))
        current = _current_weight(root, row)
        current_notional = current * capital if current is not None else None
        target_notional = target * capital if target is not None else None
        trade = target_notional - current_notional if current_notional is not None and target_notional is not None else None
        drift = target - current if target is not None and current is not None else None
        action, reason = _line_action_and_reason(
            current_weight=current,
            target_weight=target,
            trade_notional=trade,
            drift=drift,
        )
        cost = abs(trade) * 0.0005 if action in {"INCREASE", "REDUCE"} and trade is not None else 0.0
        line_items.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": row.get("ui_name") or row.get("display_name") or row.get("name") or strategy_id,
                "state": row.get("membership_state") or row.get("current_operational_status") or "Unavailable",
                "current_weight": current,
                "target_weight": target,
                "weight_change": drift,
                "current_notional": current_notional,
                "target_notional": target_notional,
                "paper_trade_notional": trade,
                "action": action,
                "reason": reason,
                "estimated_transaction_cost": cost,
                "cost_assumption": COST_ASSUMPTION,
                "execution_mode": EXECUTION_MODE,
                "live_brokerage_fill": LIVE_BROKERAGE_FILL,
                "official_ledger_mutation": OFFICIAL_LEDGER_MUTATION,
            }
        )

    material = [row for row in line_items if row["action"] in {"INCREASE", "REDUCE"}]
    review = any(row["action"] == "REVIEW" for row in line_items)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": f"paper-rebalance-{uuid4().hex[:12]}",
        "created_at": _now_iso(),
        "source_label": SOURCE_LABEL,
        "status": "Review" if review else "Draft",
        "applied_status": "Draft",
        "intended_effective_date": intended_effective_date or next_business_day(_as_of_date(snapshot)),
        "target_total": total,
        "residual_cash_weight": max(0.0, 1.0 - total),
        "active_sleeve_count": len(sleeves),
        "line_items": line_items,
        "paper_trade_notional_total": sum(abs(row["paper_trade_notional"] or 0.0) for row in material),
        "paper_transaction_cost_total": sum(float(row["estimated_transaction_cost"] or 0.0) for row in material),
        "cost_assumption": COST_ASSUMPTION,
        "execution_mode": EXECUTION_MODE,
        "live_brokerage_fill": LIVE_BROKERAGE_FILL,
        "official_ledger_mutation": OFFICIAL_LEDGER_MUTATION,
        "paper_only": True,
    }
    return _persist_plan(root, plan)


def accept_paper_rebalance_plan(root: Path, plan_id: str) -> dict[str, Any]:
    plan, plans = _load_plan(root, plan_id)
    if any(row.get("action") == "REVIEW" for row in plan.get("line_items") or []):
        raise ValueError("review lines must be resolved before accepting a paper rebalance plan")
    if float(plan.get("target_total") or 0.0) > 1.0001:
        raise ValueError("over-allocated paper target cannot be accepted")
    updated = deepcopy(plan)
    updated["status"] = "Accepted Pending Application"
    updated["applied_status"] = "Accepted Pending Application"
    updated["accepted_at"] = _now_iso()
    plans = [updated if row.get("plan_id") == plan_id else row for row in plans]
    _write_plans(root, plans)
    return updated


def apply_paper_rebalance_plan(root: Path, plan_id: str) -> dict[str, Any]:
    plan, plans = _load_plan(root, plan_id)
    if plan.get("applied_status") != "Accepted Pending Application":
        raise ValueError("paper rebalance plan must be accepted before application")
    if any(row.get("action") == "REVIEW" for row in plan.get("line_items") or []):
        raise ValueError("review lines block paper allocation application")
    applied_at = _now_iso()
    weights = {
        row["strategy_id"]: row["target_weight"]
        for row in plan.get("line_items") or []
        if row.get("target_weight") is not None
    }
    target_payload = {
        "schema_version": SCHEMA_VERSION,
        "source_label": SOURCE_LABEL,
        "applied_plan_id": plan_id,
        "applied_at": applied_at,
        "intended_effective_date": plan.get("intended_effective_date"),
        "applied_status": "Applied to Paper Allocation",
        "weights": weights,
        "target_total": plan.get("target_total"),
        "residual_cash_weight": plan.get("residual_cash_weight"),
        "active_sleeve_count": plan.get("active_sleeve_count"),
        "paper_transaction_cost_total": plan.get("paper_transaction_cost_total"),
        "paper_trade_notional_total": plan.get("paper_trade_notional_total"),
        "cost_assumption": COST_ASSUMPTION,
        "execution_mode": EXECUTION_MODE,
        "live_brokerage_fill": LIVE_BROKERAGE_FILL,
        "official_ledger_mutation": OFFICIAL_LEDGER_MUTATION,
        "paper_only": True,
    }
    _atomic_write_json(_paths(root)["target"], target_payload)

    cost_store = _cost_store(root)
    cost_record = {
        "schema_version": SCHEMA_VERSION,
        "cost_record_id": f"paper-cost-{uuid4().hex[:12]}",
        "plan_id": plan_id,
        "applied_at": applied_at,
        "intended_effective_date": plan.get("intended_effective_date"),
        "paper_transaction_cost_total": plan.get("paper_transaction_cost_total"),
        "paper_trade_notional_total": plan.get("paper_trade_notional_total"),
        "active_sleeve_count": plan.get("active_sleeve_count"),
        "cost_assumption": COST_ASSUMPTION,
        "execution_mode": EXECUTION_MODE,
        "live_brokerage_fill": LIVE_BROKERAGE_FILL,
        "official_ledger_mutation": OFFICIAL_LEDGER_MUTATION,
        "paper_only": True,
    }
    costs = cost_store.get("costs") or []
    costs.append(cost_record)
    _atomic_write_json(_paths(root)["costs"], {"schema_version": SCHEMA_VERSION, "costs": costs})

    updated = deepcopy(plan)
    updated["status"] = "Applied to Paper Allocation"
    updated["applied_status"] = "Applied to Paper Allocation"
    updated["applied_at"] = applied_at
    plans = [updated if row.get("plan_id") == plan_id else row for row in plans]
    _write_plans(root, plans)
    return {"plan": updated, "current_paper_target": target_payload, "cost_record": cost_record}


def reject_paper_rebalance_plan(root: Path, plan_id: str) -> dict[str, Any]:
    plan, plans = _load_plan(root, plan_id)
    updated = deepcopy(plan)
    updated["status"] = "Rejected"
    updated["applied_status"] = "Rejected"
    updated["rejected_at"] = _now_iso()
    plans = [updated if row.get("plan_id") == plan_id else row for row in plans]
    _write_plans(root, plans)
    return updated


def paper_rebalance_snapshot_payload(root: Path) -> dict[str, Any]:
    plans = _plan_store(root).get("plans") or []
    costs = _cost_store(root).get("costs") or []
    current = _current_target(root)
    latest_plan = plans[-1] if plans else None
    latest_applied = next(
        (row for row in reversed(plans) if row.get("applied_status") == "Applied to Paper Allocation"),
        None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_paths": {
            "current_paper_target_weights": "data/paper_rebalance/current_paper_target_weights.json",
            "paper_rebalance_plans": "data/paper_rebalance/paper_rebalance_plans.json",
            "paper_rebalance_costs": "data/paper_rebalance/paper_rebalance_costs.json",
        },
        "current_paper_target": current,
        "plans": plans,
        "costs": costs,
        "latest_plan": latest_plan,
        "latest_applied": latest_applied,
        "latest_cost_record": costs[-1] if costs else None,
        "paper_only": True,
        "execution_mode": EXECUTION_MODE,
        "live_brokerage_fill": LIVE_BROKERAGE_FILL,
        "official_ledger_mutation": OFFICIAL_LEDGER_MUTATION,
        "brokerage_execution": "Disabled",
    }
