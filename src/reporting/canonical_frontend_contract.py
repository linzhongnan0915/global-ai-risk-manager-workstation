"""Canonical operational frontend contract for the local risk workstation."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any
import json


CONTRACT_VERSION = "2.0.0"
COMBINED_STRATEGY_ID = "COMBINED_PORTFOLIO"
MASTER_PORTFOLIO_ID = "MASTER_PORTFOLIO"
LEGACY_INTERNAL_ID_PREFIXES = ("STRAT_", "PROTO_", "CAND_")
LEGACY_NAMES = {
    "Liquid Alternative Factor Premia Clone",
    "Business-Cycle Regime Allocation",
    "High-Volatility Regime Defensive Switch",
    "Managed Futures Trend Proxy",
    "Convertible Arbitrage Proxy",
    "Tail Hedge Crisis Sleeve",
}


class CanonicalContractError(ValueError):
    """Raised when the normalized operational contract is invalid."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _previous_day(value: str) -> str:
    return (date.fromisoformat(value) - timedelta(days=1)).isoformat()


def _strategy_records(shadow: dict[str, Any]) -> list[dict[str, Any]]:
    executed = shadow.get("strategy_summary") or []
    executed_ids = {row["strategy_id"] for row in executed}
    pending_details = shadow.get("strategy_details") or {}
    display_ids = {
        row["strategy_id"]: f"#{index:06d}"
        for index, row in enumerate(executed, start=1)
    }
    for index, strategy_id in enumerate(
        (strategy_id for strategy_id in pending_details if strategy_id not in executed_ids),
        start=len(executed) + 2,
    ):
        display_ids[strategy_id] = f"#{index:06d}"

    current_underlying_ids = [row["strategy_id"] for row in executed]
    approved_underlying_ids = current_underlying_ids + [
        strategy_id for strategy_id in pending_details if strategy_id not in executed_ids
    ]
    current_outer_weight = 1.0 / (len(current_underlying_ids) + 1)
    approved_outer_weight = 1.0 / (len(approved_underlying_ids) + 1)
    records: list[dict[str, Any]] = [
        {
            "internal_id": COMBINED_STRATEGY_ID,
            "display_id": "#COMBINED",
            "name": "Combined",
            "membership_state": "executed",
            "operational_state": "executed",
            "effective_from": None,
            "current_weight": current_outer_weight,
            "data_status": "DATA_PENDING",
            "validation_status": "ACTIVE_COMPOSITE",
            "latest_signal_date": shadow.get("latest_valid_target_position_date"),
            "daily_return": None,
            "daily_pnl": None,
            "cumulative_return": None,
            "cumulative_pnl": None,
            "current_drawdown": None,
            "live_allocation_approved": False,
            "execution_enabled": False,
            "research_evidence_available": True,
            "constituent_internal_ids": current_underlying_ids,
            "constituent_count": len(current_underlying_ids),
            "constituent_equal_weight": 1.0 / len(current_underlying_ids),
            "approved_constituent_internal_ids": approved_underlying_ids,
            "approved_constituent_count": len(approved_underlying_ids),
            "approved_constituent_equal_weight": 1.0 / len(approved_underlying_ids),
        }
    ]
    for row in executed:
        records.append(
            {
                "internal_id": row["strategy_id"],
                "display_id": display_ids[row["strategy_id"]],
                "name": row.get("strategy_name"),
                "membership_state": "executed",
                "operational_state": "executed",
                "effective_from": None,
                "current_weight": current_outer_weight,
                "data_status": row.get("data_status"),
                "validation_status": row.get("validation_status"),
                "latest_signal_date": row.get("latest_signal_date"),
                "daily_return": row.get("net_return"),
                "daily_pnl": row.get("daily_pnl"),
                "cumulative_return": row.get("cumulative_return"),
                "cumulative_pnl": row.get("cumulative_pnl"),
                "current_drawdown": row.get("current_drawdown"),
                "live_allocation_approved": row.get("live_allocation_approved"),
                "execution_enabled": row.get("execution_enabled"),
                "research_evidence_available": False,
            }
        )

    for strategy_id, details in pending_details.items():
        if strategy_id in executed_ids:
            continue
        records.append(
            {
                "internal_id": strategy_id,
                "display_id": display_ids[strategy_id],
                "name": details.get("name"),
                "membership_state": "approved_pending",
                "operational_state": "approved_pending",
                "effective_from": details.get("membership_effective_date") or shadow.get("membership_effective_date"),
                "current_weight": None,
                "proposed_post_admission_weight": approved_outer_weight,
                "data_status": "PENDING_EFFECTIVE_DATE",
                "validation_status": details.get("validation_status"),
                "latest_signal_date": None,
                "daily_return": None,
                "daily_pnl": None,
                "cumulative_return": None,
                "cumulative_pnl": None,
                "current_drawdown": None,
                "live_allocation_approved": details.get("live_allocation_approved", False),
                "execution_enabled": False,
                "research_evidence_available": bool(details.get("research_metrics")),
            }
        )
    return records


def _membership_timeline(bundle: dict[str, Any], strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shadow = bundle["shadow_live"]
    effective_date = shadow["membership_effective_date"]
    executed_ids = [row["internal_id"] for row in strategies if row["membership_state"] == "executed"]
    pending_ids = [row["internal_id"] for row in strategies if row["membership_state"] == "approved_pending"]
    return [
        {
            "effective_from": bundle["start_date"],
            "effective_to": _previous_day(effective_date),
            "state": "executed",
            "member_internal_ids": executed_ids,
            "n": len(executed_ids),
            "equal_weight": 1.0 / len(executed_ids),
        },
        {
            "effective_from": effective_date,
            "effective_to": None,
            "state": "approved_pending",
            "member_internal_ids": executed_ids + pending_ids,
            "n": len(executed_ids + pending_ids),
            "equal_weight": 1.0 / len(executed_ids + pending_ids),
        },
    ]


def build_canonical_frontend_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    """Normalize the committed shadow-live bundle without inventing values."""
    if not isinstance(bundle.get("shadow_live"), dict):
        raise CanonicalContractError("shadow_live operational source is required")
    shadow = bundle["shadow_live"]
    strategies = _strategy_records(shadow)
    portfolio_daily = deepcopy(shadow.get("portfolio_ledger") or [])
    latest = portfolio_daily[-1] if portfolio_daily else {}
    pending_ids = [row["internal_id"] for row in strategies if row["membership_state"] == "approved_pending"]
    contract = {
        "contract_version": CONTRACT_VERSION,
        "source": {
            "location": "dashboard/data/shadow_live_bundle.json",
            "classification": "canonical_operational",
            "committed_local_only": True,
        },
        "portfolio_summary": {
            "portfolio_id": MASTER_PORTFOLIO_ID,
            "name": "Master Portfolio",
            "as_of_date": bundle.get("market_as_of"),
            "start_date": bundle.get("start_date"),
            "nav": latest.get("ending_nav"),
            "latest_net_pnl": latest.get("net_pnl"),
            "cumulative_pnl": latest.get("cumulative_pnl"),
            "cumulative_return": latest.get("cumulative_return"),
            "current_drawdown": latest.get("current_drawdown"),
            "current_n": int(latest.get("active_count") or shadow.get("previous_active_count") or 0) + 1,
            "current_equal_weight": 1.0 / (int(latest.get("active_count") or shadow.get("previous_active_count") or 0) + 1),
            "approved_n": int(shadow.get("current_active_count") or 0) + 1,
            "approved_equal_weight": 1.0 / (int(shadow.get("current_active_count") or 0) + 1),
            "current_underlying_n": int(latest.get("active_count") or shadow.get("previous_active_count") or 0),
            "approved_underlying_n": int(shadow.get("current_active_count") or 0),
            "data_status": latest.get("data_quality_status"),
            "research_only": True,
            "live_allocation_percent": bundle.get("live_capital_percent"),
            "live_allocation_approved": bundle.get("live_allocation_approved"),
            "execution_enabled": bundle.get("execution_enabled"),
        },
        "membership_timeline": _membership_timeline(bundle, strategies),
        "strategies": strategies,
        "portfolio_daily": portfolio_daily,
        "strategy_daily": deepcopy(shadow.get("strategy_ledger") or shadow.get("strategy_summary") or []),
        "holdings": deepcopy(shadow.get("holdings") or []),
        "trades": deepcopy(shadow.get("trades") or []),
        "operational_status": {
            "runner_mode": shadow.get("runner_mode"),
            "configured_strategy_count": shadow.get("configured_strategy_count"),
            "successful_strategy_count": shadow.get("successful_strategy_count"),
            "partial_strategy_count": shadow.get("partial_strategy_count"),
            "unavailable_strategy_count": shadow.get("unavailable_strategy_count"),
            "latest_raw_data_timestamp": shadow.get("latest_raw_data_timestamp"),
            "latest_valid_target_position_date": shadow.get("latest_valid_target_position_date"),
            "latest_simulated_execution_date": shadow.get("latest_simulated_execution_date"),
            "last_successful_run": shadow.get("last_successful_run"),
            "correlation": deepcopy(shadow.get("correlation") or {}),
        },
        "alerts": deepcopy(shadow.get("alerts") or []),
        "pending_membership": [
            {
                "internal_id": strategy_id,
                "effective_from": shadow.get("membership_effective_date"),
                "state": "approved_pending",
                "pending_target_count": sum(
                    row.get("strategy_id") == strategy_id for row in shadow.get("pending_targets") or []
                ),
                "research_evidence_available": next(
                    row["research_evidence_available"] for row in strategies if row["internal_id"] == strategy_id
                ),
                "live_allocation_approved": False,
                "execution_enabled": False,
            }
            for strategy_id in pending_ids
        ],
    }
    validate_canonical_frontend_contract(contract)
    return contract


def validate_canonical_frontend_contract(contract: dict[str, Any]) -> None:
    """Validate semantic invariants required by all current operational views."""
    required = {
        "portfolio_summary",
        "membership_timeline",
        "strategies",
        "portfolio_daily",
        "strategy_daily",
        "holdings",
        "trades",
        "operational_status",
        "alerts",
        "pending_membership",
    }
    missing = required - set(contract)
    if missing:
        raise CanonicalContractError(f"missing contract sections: {sorted(missing)}")

    strategies = contract["strategies"]
    internal_ids = [row["internal_id"] for row in strategies]
    display_ids = [row["display_id"] for row in strategies]
    names = [row.get("name") for row in strategies]
    if len(internal_ids) != len(set(internal_ids)):
        raise CanonicalContractError("strategy internal IDs must be unique")
    if len(display_ids) != len(set(display_ids)):
        raise CanonicalContractError("strategy display IDs must be unique")
    if any(strategy_id.startswith(LEGACY_INTERNAL_ID_PREFIXES) for strategy_id in internal_ids):
        raise CanonicalContractError("legacy proxy strategy entered canonical contract")
    if LEGACY_NAMES.intersection(name for name in names if name):
        raise CanonicalContractError("legacy proxy strategy name entered canonical contract")
    if any(row.get("internal_id") == row.get("name") for row in strategies):
        raise CanonicalContractError("internal strategy ID and display name must remain separate")

    for state in contract["membership_timeline"]:
        if state["n"] != len(state["member_internal_ids"]):
            raise CanonicalContractError("membership count does not match members")
        if abs(state["n"] * state["equal_weight"] - 1.0) > 1e-8:
            raise CanonicalContractError("membership weights must sum to one")
    if [state["n"] for state in contract["membership_timeline"]] != [17, 18]:
        raise CanonicalContractError("expected outer portfolio N=17 then N=18 membership")


def build_from_path(source_path: Path) -> dict[str, Any]:
    return build_canonical_frontend_contract(_load_json(source_path))
