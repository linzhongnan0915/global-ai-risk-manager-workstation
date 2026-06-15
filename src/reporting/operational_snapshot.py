"""Versioned operational snapshot and local decision audit for Command Center."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from src.market.intraday_provider import fetch_intraday_bars, latest_bar_by_ticker
from src.market.market_hours import market_session_status
from src.reporting.strategy_research_artifacts import load_strategy_research_artifacts
from src.strategies.display_metadata import strategy_display_metadata


SNAPSHOT_VERSION = "3.6.6"
REFRESH_INTERVAL_SECONDS = 300
INITIAL_SHADOW_CAPITAL = 1_000_000.0
EXPECTED_ORDINARY_ACTIVE_SLEEVES = 16
TOP_LEVEL_ACTIVE_SLEEVES = 17
PENDING_POST_ADMISSION_SLEEVES = 18
INITIAL_SLEEVE_CAPITAL = INITIAL_SHADOW_CAPITAL / TOP_LEVEL_ACTIVE_SLEEVES
PROVENANCE_STATES = {
    "VERIFIED_SHADOW_EXECUTION",
    "RECONSTRUCTED_PAPER_BACKFILL",
    "PENDING_EXECUTION",
    "PRE_OPERATIONAL",
    "INVALID_EXECUTION_RECORD",
}
PROVENANCE_LABELS = {
    "VERIFIED_SHADOW_EXECUTION": "Shadow Execution / Paper Fill",
    "RECONSTRUCTED_PAPER_BACKFILL": "Reconstructed Paper Record / Retrospective Paper Backfill",
    "PENDING_EXECUTION": "Pending Execution",
    "PRE_OPERATIONAL": "Pre-Operational",
    "INVALID_EXECUTION_RECORD": "Invalid Execution Record",
}


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else deepcopy(default)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def snapshot_refresh_lock(path: Path):
    acquired = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        acquired = True
        yield True
    except FileExistsError:
        yield False
    finally:
        if acquired:
            path.unlink(missing_ok=True)


def _paths(root: Path) -> dict[str, Path]:
    return {
        "canonical": root / "dashboard/data/canonical_operational.json",
        "source_bundle": root / "dashboard/data/shadow_live_bundle.json",
        "snapshot": root / "output/operational_snapshot.json",
        "status": root / "output/operational_refresh_status.json",
        "lock": root / "output/operational_snapshot.lock",
        "decisions": root / "output/command_center_decisions.json",
    }


def _current_holdings(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_date = max((row.get("date") or "" for row in holdings), default="")
    return [deepcopy(row) for row in holdings if row.get("date") == latest_date]


def _max_drawdown(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row["current_drawdown"]) for row in rows if row.get("current_drawdown") is not None]
    return min(values) if values else None


def classify_execution_provenance(row: dict[str, Any]) -> str:
    """Classify from source evidence, never from a presentation label alone."""
    record_label = row.get("record_label")
    if record_label == "RETROSPECTIVE_PAPER_BACKFILL":
        return "RECONSTRUCTED_PAPER_BACKFILL"
    if row.get("data_status") == "PENDING_EXECUTION" or not row.get("execution_date") and row.get("expected_execution_date"):
        return "PENDING_EXECUTION"
    signal_as_of = row.get("signal_as_of_date") or row.get("signal_date")
    data_cutoff = row.get("data_cutoff") or row.get("signal_generated_at")
    target_effective = row.get("target_effective_date")
    execution_date = row.get("execution_date") or row.get("date")
    convention = row.get("execution_convention")
    price_source = row.get("execution_price_source") or row.get("reference_price_source")
    complete = all((signal_as_of, data_cutoff, target_effective, execution_date, convention, price_source))
    if complete and str(signal_as_of) < str(execution_date) and str(data_cutoff) < str(execution_date):
        return "VERIFIED_SHADOW_EXECUTION"
    return "INVALID_EXECUTION_RECORD"


def _first_date(rows: list[dict[str, Any]], *, status: str | None = None) -> str | None:
    dates = [
        row.get("date") or row.get("execution_date")
        for row in rows
        if (status is None or row.get("execution_provenance") == status)
        and (row.get("date") or row.get("execution_date"))
    ]
    return min(dates) if dates else None


def _correct_strategy_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild operational analytics from the correct independent top-level sleeve capital."""
    nav = INITIAL_SLEEVE_CAPITAL
    peak = nav
    corrected = []
    for source in sorted(rows, key=lambda row: row.get("date") or ""):
        row = deepcopy(source)
        row["execution_provenance"] = classify_execution_provenance(row)
        row["execution_provenance_label"] = PROVENANCE_LABELS[row["execution_provenance"]]
        beginning = nav
        gross_pnl = float(row.get("gross_return") or 0) * beginning
        cost = float(row.get("transaction_cost") or 0)
        daily_pnl = gross_pnl - cost
        nav = beginning + daily_pnl
        peak = max(peak, nav)
        row.update({
            "capital_basis": "TOP_LEVEL_17_AVAILABLE_LEDGER_ANALYTICS",
            "beginning_sleeve_nav": beginning,
            "ending_sleeve_nav": nav,
            "daily_pnl": daily_pnl,
            "net_return": daily_pnl / beginning if beginning else None,
            "cumulative_pnl": nav - INITIAL_SLEEVE_CAPITAL,
            "cumulative_return": nav / INITIAL_SLEEVE_CAPITAL - 1,
            "running_peak": peak,
            "current_drawdown": nav / peak - 1,
        })
        corrected.append(row)
    return corrected


def _combined_strategy_history(
    histories_by_id: dict[str, list[dict[str, Any]]],
    member_ids: list[str],
) -> list[dict[str, Any]]:
    """Derive Combined from ordinary operational net returns without adding trade cost rows."""
    members = [strategy_id for strategy_id in member_ids if strategy_id in histories_by_id]
    if not members:
        return []
    rows_by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for strategy_id in members:
        for row in histories_by_id[strategy_id]:
            if row.get("date") and row.get("net_return") is not None:
                rows_by_date.setdefault(row["date"], {})[strategy_id] = row
    nav = INITIAL_SLEEVE_CAPITAL
    peak = nav
    derived = []
    for date_value in sorted(rows_by_date):
        member_rows = rows_by_date[date_value]
        if len(member_rows) != len(members):
            continue
        beginning = nav
        net_return = sum(float(row["net_return"]) for row in member_rows.values()) / len(members)
        daily_pnl = beginning * net_return
        nav = beginning + daily_pnl
        peak = max(peak, nav)
        provenance_counts = {
            state: sum(row.get("execution_provenance") == state for row in member_rows.values())
            for state in PROVENANCE_STATES
        }
        provenance = (
            "RECONSTRUCTED_PAPER_BACKFILL"
            if provenance_counts["RECONSTRUCTED_PAPER_BACKFILL"] == len(members)
            else "INVALID_EXECUTION_RECORD"
        )
        derived.append(
            {
                "strategy_id": "COMBINED_PORTFOLIO",
                "date": date_value,
                "record_label": "DERIVED_FROM_ORDINARY_OPERATIONAL_LEDGERS",
                "execution_provenance": provenance,
                "execution_provenance_label": PROVENANCE_LABELS[provenance],
                "capital_basis": "TOP_LEVEL_17_AVAILABLE_LEDGER_DERIVED_COMBINED_OPERATIONAL_LEDGER",
                "beginning_sleeve_nav": beginning,
                "ending_sleeve_nav": nav,
                "gross_return": net_return,
                "transaction_cost": None,
                "daily_pnl": daily_pnl,
                "net_return": net_return,
                "cumulative_pnl": nav - INITIAL_SLEEVE_CAPITAL,
                "cumulative_return": nav / INITIAL_SLEEVE_CAPITAL - 1,
                "running_peak": peak,
                "current_drawdown": nav / peak - 1,
                "constituent_count": len(members),
                "member_internal_ids": members,
                "cost_treatment": "Derived from ordinary strategy net returns; no separate Combined trade ledger and no cost double count.",
            }
        )
    return derived


def _entity_inventory(
    strategies: list[dict[str, Any]],
    history_by_id: dict[str, list[dict[str, Any]]],
    trade_by_id: dict[str, list[dict[str, Any]]],
    holding_by_id: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    expected_slots = [f"#{index:06d}" for index in range(1, EXPECTED_ORDINARY_ACTIVE_SLEEVES + 1)]
    by_display = {row.get("display_id"): row for row in strategies}
    entities: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for display_id in expected_slots:
        row = by_display.get(display_id)
        if not row:
            continue
        strategy_id = row["internal_id"]
        entities.append({
            "display_id": display_id,
            "internal_id": strategy_id,
            "strategy_name": row.get("display_name") or row.get("name"),
            "entity_type": "ORDINARY_STRATEGY",
            "current_operational_status": row.get("current_operational_status"),
            "has_operational_daily_ledger": bool(history_by_id.get(strategy_id)),
            "has_trade_rows": bool(trade_by_id.get(strategy_id)),
            "has_holdings_position_rows": bool(holding_by_id.get(strategy_id)),
            "has_research_artifacts": bool(row.get("research_evidence")),
            "effective_date": row.get("strategy_effective_date"),
            "blocker": None if history_by_id.get(strategy_id) else "No operational daily ledger rows are present.",
        })
    combined = next((row for row in strategies if row["internal_id"] == "COMBINED_PORTFOLIO"), None)
    if combined:
        entities.append({
            "display_id": combined["display_id"],
            "internal_id": combined["internal_id"],
            "strategy_name": combined.get("display_name") or combined.get("name"),
            "entity_type": "COMBINED_STRATEGY",
            "current_operational_status": combined.get("current_operational_status"),
            "has_operational_daily_ledger": bool(history_by_id.get(combined["internal_id"])),
            "has_trade_rows": bool(trade_by_id.get(combined["internal_id"])),
            "has_holdings_position_rows": bool(holding_by_id.get(combined["internal_id"])),
            "has_research_artifacts": bool(combined.get("research_evidence")),
            "effective_date": combined.get("strategy_effective_date"),
            "blocker": combined.get("cost_treatment"),
        })
    for row in strategies:
        if row.get("membership_state") != "approved_pending":
            continue
        strategy_id = row["internal_id"]
        entities.append({
            "display_id": row["display_id"],
            "internal_id": strategy_id,
            "strategy_name": row.get("display_name") or row.get("name"),
            "entity_type": "PENDING_CANDIDATE",
            "current_operational_status": row.get("current_operational_status"),
            "has_operational_daily_ledger": bool(history_by_id.get(strategy_id)),
            "has_trade_rows": bool(trade_by_id.get(strategy_id)),
            "has_holdings_position_rows": bool(holding_by_id.get(strategy_id)),
            "has_research_artifacts": bool(row.get("research_evidence")),
            "effective_date": row.get("strategy_effective_date"),
            "blocker": row.get("exact_blocker"),
        })
    ordinary_with_ledger = [
        row for row in entities
        if row["entity_type"] == "ORDINARY_STRATEGY" and row["has_operational_daily_ledger"]
    ]
    return {
        "entities": entities,
        "ordinary_entities": len(expected_slots),
        "ordinary_operational_ledgers": len(ordinary_with_ledger),
        "combined": 1 if combined else 0,
        "pending_candidates": sum(row["entity_type"] == "PENDING_CANDIDATE" for row in entities),
        "total_registry_entities": len(entities),
        "missing_ordinary_ledger": missing,
        "status": "PASS" if not missing else "FAIL_WITH_DATA_BLOCKER",
    }


def _last_rebalance(strategy_id: str, trades: list[dict[str, Any]], first_record_date: str | None) -> str | None:
    dates = sorted(
        {
            row["execution_date"]
            for row in trades
            if row.get("strategy_id") == strategy_id
            and row.get("record_status") == "SIMULATED"
            and abs(float(row.get("delta_weight") or 0)) > 0
        }
    )
    return dates[-1] if dates else first_record_date


def _official_contributors(strategies: list[dict[str, Any]], limit: int = 4) -> tuple[list[dict], list[dict]]:
    value_key = "estimated_daily_pnl" if any(row.get("estimated_daily_pnl") is not None for row in strategies) else "daily_pnl"
    available = [row for row in strategies if row.get(value_key) is not None]
    winners = sorted(available, key=lambda row: row[value_key], reverse=True)[:limit]
    losers = sorted(available, key=lambda row: row[value_key])[:limit]
    displayed = winners + losers
    denominator = max((abs(float(row[value_key])) for row in displayed), default=0.0)

    def enrich(row: dict[str, Any]) -> dict[str, Any]:
        value = float(row[value_key])
        return {
            "internal_id": row["internal_id"],
            "display_id": row["display_id"],
            "display_name": row["display_name"],
            "daily_pnl": value,
            "contribution_basis": "INTRADAY_ESTIMATE" if value_key == "estimated_daily_pnl" else "OFFICIAL_DAILY",
            "bar_width_percent": abs(value) / denominator * 100 if denominator else 0.0,
        }

    return [enrich(row) for row in winners], [enrich(row) for row in losers]


def _proposal_state(strategies: list[dict[str, Any]], portfolio: dict[str, Any], decisions: list[dict]) -> dict:
    accepted = [row for row in strategies if row["membership_state"] in {"executed", "approved_pending"}]
    proposed = {row["internal_id"]: portfolio["approved_equal_weight"] for row in accepted}
    operational_decisions = [row for row in decisions if row.get("environment", "OPERATIONAL") != "TEST"]
    latest = operational_decisions[-1] if operational_decisions else None
    if latest and latest.get("new_proposed_weights"):
        proposed = latest["new_proposed_weights"]
    return {
        "status": latest.get("status") if latest else "PENDING_HUMAN_APPROVAL",
        "proposed_effective_date": min(
            (row.get("effective_from") for row in accepted if row.get("effective_from")),
            default=None,
        ),
        "proposed_weights": proposed,
        "latest_decision_id": latest.get("decision_id") if latest else None,
        "execution_authorized": False,
    }


def _wq_admission_gate(canonical: dict[str, Any]) -> dict[str, Any]:
    """Gate WQ on canonical execution evidence only, not research validation text."""
    strategy_id = "WQ_ALPHA_018"
    pending = next(
        (row for row in canonical.get("pending_membership", []) if row.get("internal_id") == strategy_id),
        {},
    )
    strategy = next(
        (row for row in canonical.get("strategies", []) if row.get("internal_id") == strategy_id),
        {},
    )
    as_of_date = canonical.get("portfolio_summary", {}).get("as_of_date")
    trades = [row for row in canonical.get("trades", []) if row.get("strategy_id") == strategy_id]
    holdings = [row for row in canonical.get("holdings", []) if row.get("strategy_id") == strategy_id]
    strategy_daily = [row for row in canonical.get("strategy_daily", []) if row.get("strategy_id") == strategy_id]
    effective_from = pending.get("effective_from") or strategy.get("effective_from")
    execution_rows = [
        row for row in trades
        if classify_execution_provenance(row) == "VERIFIED_SHADOW_EXECUTION"
    ]
    evidence = {
        "approval_record": bool(pending or strategy.get("membership_state") == "approved_pending"),
        "membership_effective_date": effective_from,
        "membership_effective_reached_in_canonical": bool(effective_from and as_of_date and as_of_date >= effective_from),
        "canonical_signal_date": strategy.get("latest_signal_date"),
        "canonical_target_rows": 0,
        "canonical_trade_rows": len(trades),
        "canonical_position_rows": len(holdings),
        "canonical_strategy_daily_rows": len(strategy_daily),
        "verified_execution_rows": len(execution_rows),
        "market_reference_price_source": any(
            row.get("execution_price_source") or row.get("reference_price_source") or row.get("simulated_execution_price")
            for row in trades
        ),
        "brokerage_execution": "Disabled",
        "live_allocation_approved": bool(strategy.get("live_allocation_approved")),
        "execution_enabled": bool(strategy.get("execution_enabled")),
    }
    blockers = []
    if not evidence["membership_effective_reached_in_canonical"]:
        blockers.append(
            f"Membership effective date {effective_from or 'N/A'} is after canonical portfolio as-of {as_of_date or 'N/A'}."
        )
    if not evidence["canonical_signal_date"]:
        blockers.append("No canonical WQ signal date is present.")
    if evidence["canonical_target_rows"] == 0:
        blockers.append("No canonical WQ target-position artifact is present.")
    if evidence["canonical_trade_rows"] == 0:
        blockers.append("No canonical WQ Paper Execution / Paper Fill rows are present.")
    if evidence["canonical_position_rows"] == 0:
        blockers.append("No canonical WQ position rows are present.")
    if evidence["verified_execution_rows"] == 0:
        blockers.append("No WQ record satisfies VERIFIED_SHADOW_EXECUTION provenance.")
    admitted = not blockers
    return {
        "strategy_id": strategy_id,
        "status": "ADMITTED" if admitted else "APPROVED_PENDING",
        "current_operational_status": "VERIFIED_SHADOW_EXECUTION" if admitted else "PRE_OPERATIONAL",
        "admitted_to_combined": admitted,
        "combined_rebalance_allowed": admitted,
        "current_executed_count": canonical.get("portfolio_summary", {}).get("current_n"),
        "approved_pending_count": sum(
            1 for row in canonical.get("strategies", []) if row.get("membership_state") == "approved_pending"
        ),
        "combined_constituents": canonical.get("portfolio_summary", {}).get("current_underlying_n"),
        "required_provenance_state": "VERIFIED_SHADOW_EXECUTION",
        "evidence": evidence,
        "blockers": blockers,
        "exact_blocker": " | ".join(blockers) if blockers else None,
    }


def build_operational_snapshot(
    canonical: dict[str, Any],
    *,
    intraday: dict[str, Any] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    operational_pricing_universe_size: int | None = None,
    strategy_research_details: dict[str, Any] | None = None,
    generated_at: str | None = None,
    refresh_status: str = "BASELINE",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Build the API snapshot while keeping official and intraday accounting separate."""
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    portfolio_daily = []
    for source_row in canonical["portfolio_daily"]:
        row = deepcopy(source_row)
        row["official_close_date"] = row.get("data_as_of") or row.get("return_end_date") or row.get("date")
        row["execution_provenance"] = classify_execution_provenance(row)
        row["execution_provenance_label"] = PROVENANCE_LABELS[row["execution_provenance"]]
        portfolio_daily.append(row)
    trades = []
    for source_trade in canonical["trades"]:
        trade = deepcopy(source_trade)
        action = trade.get("action")
        cost = trade.get("transaction_cost_amount")
        trade.update(
            {
                "quantity": trade.get("simulated_quantity"),
                "reference_execution_price": trade.get("simulated_execution_price"),
                "notional": trade.get("simulated_notional"),
                "buy_cost": cost if action in {"BUY", "COVER"} else None,
                "sell_cost": cost if action in {"SELL", "SHORT"} else None,
                "total_cost": cost,
                "status": "Completed Paper Fill" if trade.get("record_status") == "SIMULATED" else trade.get("record_status"),
                "fill_type": "Paper Fill" if trade.get("fill_status") == "NO LIVE FILL" else trade.get("fill_status"),
                "brokerage_fill": "No Live Brokerage Fill",
            }
        )
        trade["execution_provenance"] = classify_execution_provenance(trade)
        trade["execution_provenance_label"] = PROVENANCE_LABELS[trade["execution_provenance"]]
        if trade["execution_provenance"] != "VERIFIED_SHADOW_EXECUTION":
            trade["status"] = trade["execution_provenance"].replace("_", " ").title()
            trade["fill_type"] = "No Verified Paper Fill"
        trades.append(trade)
    holdings = _current_holdings(canonical["holdings"])
    published_holdings = (intraday or {}).get("holdings") or holdings
    metadata = strategy_display_metadata(canonical["strategies"])
    metadata_by_id = {row["internal_id"]: row for row in metadata}
    research_by_id = strategy_research_details or {}
    raw_strategy_daily = deepcopy(canonical["strategy_daily"])
    raw_history_by_id: dict[str, list[dict]] = {}
    for row in raw_strategy_daily:
        raw_history_by_id.setdefault(row["strategy_id"], []).append(row)
    strategy_daily = [
        row
        for strategy_id, rows in raw_history_by_id.items()
        for row in _correct_strategy_history(rows)
    ]
    corrected_history_by_id: dict[str, list[dict]] = {}
    for row in strategy_daily:
        corrected_history_by_id.setdefault(row["strategy_id"], []).append(row)
    combined_source = next(
        (row for row in canonical["strategies"] if row.get("internal_id") == "COMBINED_PORTFOLIO"),
        {},
    )
    combined_member_ids = [
        strategy_id
        for strategy_id in combined_source.get("constituent_internal_ids", [])
        if strategy_id != "COMBINED_PORTFOLIO" and strategy_id != "WQ_ALPHA_018"
    ]
    strategy_daily.extend(_combined_strategy_history(corrected_history_by_id, combined_member_ids))
    daily_by_id = {row["strategy_id"]: row for row in strategy_daily}
    history_by_id: dict[str, list[dict]] = {}
    for row in strategy_daily:
        history_by_id.setdefault(row["strategy_id"], []).append(row)
    trade_by_id: dict[str, list[dict]] = {}
    holding_by_id: dict[str, list[dict]] = {}
    for row in trades:
        trade_by_id.setdefault(row["strategy_id"], []).append(row)
    for row in published_holdings:
        holding_by_id.setdefault(row["strategy_id"], []).append(row)

    strategy_intraday = dict((intraday or {}).get("strategy_contribution") or {})
    if intraday and strategy_intraday.get("COMBINED_PORTFOLIO") is None and combined_member_ids:
        member_estimates = [
            float(strategy_intraday[strategy_id])
            for strategy_id in combined_member_ids
            if strategy_intraday.get(strategy_id) is not None
        ]
        strategy_intraday["COMBINED_PORTFOLIO"] = (
            sum(member_estimates) / len(combined_member_ids)
            if len(member_estimates) == len(combined_member_ids) else None
        )
    portfolio_dates = {
        "reconstructed_portfolio_start_date": _first_date(
            portfolio_daily, status="RECONSTRUCTED_PAPER_BACKFILL"
        ),
        "verified_shadow_portfolio_start_date": _first_date(
            portfolio_daily, status="VERIFIED_SHADOW_EXECUTION"
        ),
    }
    as_of_date = canonical["portfolio_summary"].get("as_of_date")
    wq_gate = _wq_admission_gate(canonical)
    membership_effective_by_id: dict[str, str] = {}
    for state in canonical.get("membership_timeline") or []:
        for strategy_id in state.get("member_internal_ids") or []:
            effective = state.get("effective_from")
            if effective and (
                strategy_id not in membership_effective_by_id
                or effective < membership_effective_by_id[strategy_id]
            ):
                membership_effective_by_id[strategy_id] = effective
    strategies = []
    for source in canonical["strategies"]:
        internal_id = source["internal_id"]
        all_strategy_history = history_by_id.get(internal_id, [])
        first_reconstructed = _first_date(all_strategy_history, status="RECONSTRUCTED_PAPER_BACKFILL")
        first_verified = _first_date(all_strategy_history, status="VERIFIED_SHADOW_EXECUTION")
        membership_effective = source.get("effective_from") or membership_effective_by_id.get(internal_id)
        strategy_effective = (
            membership_effective
            or first_reconstructed
            or first_verified
            or (portfolio_dates["reconstructed_portfolio_start_date"] if internal_id == "COMBINED_PORTFOLIO" else None)
        )
        strategy_history = [
            row for row in all_strategy_history
            if not strategy_effective or (row.get("date") and row["date"] >= strategy_effective)
        ]
        daily = strategy_history[-1] if strategy_history else {}
        current = holding_by_id.get(internal_id, [])
        covered_current = [
            row for row in current
            if row.get("latest_price") is not None and row.get("daily_estimated_pnl") is not None
        ]
        intraday_pnl = strategy_intraday.get(internal_id)
        intraday_nav = (
            daily.get("ending_sleeve_nav") + intraday_pnl
            if daily.get("ending_sleeve_nav") is not None and intraday_pnl is not None
            else None
        )
        if source.get("membership_state") == "approved_pending":
            intraday_unavailable_reason = "Pre-operational"
        elif intraday_pnl is not None:
            intraday_unavailable_reason = None
        elif not current and internal_id != "COMBINED_PORTFOLIO":
            intraday_unavailable_reason = "No current holdings"
        elif current and len(covered_current) != len(current):
            intraday_unavailable_reason = "Price unavailable"
        else:
            intraday_unavailable_reason = "Estimate unavailable"
        current_weights = [float(row.get("target_weight") or 0) for row in current]
        strategy_trades = trade_by_id.get(internal_id, [])
        latest_execution = max((row.get("execution_date") or "" for row in strategy_trades), default=None)
        daily_cost = sum(
            float(row.get("transaction_cost_amount") or 0)
            for row in strategy_trades
            if row.get("execution_date") == latest_execution
        ) if latest_execution else None
        if strategy_effective and as_of_date and strategy_effective > as_of_date:
            current_operational_status = "PRE_OPERATIONAL"
        elif strategy_history:
            current_operational_status = strategy_history[-1]["execution_provenance"]
        else:
            current_operational_status = "PENDING_EXECUTION"
        strategy_record = {
                **deepcopy(source),
                **metadata_by_id[internal_id],
                "sleeve_weight": None if source.get("membership_state") == "approved_pending" else 1 / TOP_LEVEL_ACTIVE_SLEEVES,
                "combined_portfolio_contribution": None,
                "initial_sleeve_capital": INITIAL_SLEEVE_CAPITAL,
                "first_reconstructed_record_date": first_reconstructed,
                "first_verified_shadow_execution_date": first_verified,
                "strategy_effective_date": strategy_effective,
                "membership_effective_date": membership_effective,
                "current_operational_status": current_operational_status,
                "current_operational_label": PROVENANCE_LABELS[current_operational_status],
                "data_state": source.get("data_status"),
                "ending_nav": daily.get("ending_sleeve_nav"),
                "daily_return": daily.get("net_return"),
                "daily_pnl": daily.get("daily_pnl"),
                "cumulative_return": daily.get("cumulative_return"),
                "cumulative_pnl": daily.get("cumulative_pnl"),
                "current_drawdown": daily.get("current_drawdown"),
                "max_drawdown": None,
                "daily_turnover": daily.get("turnover"),
                "cumulative_turnover": (
                    sum(float(row["turnover"]) for row in strategy_history if row.get("turnover") is not None)
                    if strategy_history else None
                ),
                "annualized_turnover": None if daily.get("turnover") is None else float(daily["turnover"]) * 252,
                "daily_cost": daily_cost,
                "cumulative_cost": (
                    sum(float(row.get("transaction_cost_amount") or 0) for row in strategy_trades)
                    if strategy_trades else None
                ),
                "gross_pnl": (
                    sum(float(row["gross_return"]) * float(row["beginning_sleeve_nav"]) for row in strategy_history
                        if row.get("gross_return") is not None and row.get("beginning_sleeve_nav") is not None)
                    if strategy_history else None
                ),
                "net_pnl": daily.get("cumulative_pnl"),
                "observation_count": len(strategy_history),
                "operating_period_start": strategy_history[0].get("date") if strategy_history else None,
                "operating_period_end": strategy_history[-1].get("date") if strategy_history else None,
                "gross_exposure": sum(abs(value) for value in current_weights) if current else None,
                "net_exposure": sum(current_weights) if current else None,
                "long_count": sum(value > 0 for value in current_weights) if current else None,
                "short_count": sum(value < 0 for value in current_weights) if current else None,
                "holdings_count": len(current) if current else (0 if source["membership_state"] == "approved_pending" else None),
                "last_signal": source.get("latest_signal_date"),
                "last_rebalance": (
                    None if source.get("data_status") == "DATA_PENDING"
                    else _last_rebalance(internal_id, trades, _first_date(strategy_history))
                ),
                "last_execution": latest_execution,
                "estimated_daily_pnl": intraday_pnl,
                "intraday_estimated_pnl": intraday_pnl,
                "estimated_strategy_nav": intraday_nav,
                "intraday_estimated_nav": intraday_nav,
                "intraday_estimate_unavailable_reason": intraday_unavailable_reason,
                "latest_delayed_price_as_of": (intraday or {}).get("market_data_as_of"),
                "price_coverage": {
                    "priced": len(covered_current),
                    "total": len(current),
                    "status": "N/A" if not current else ("COMPLETE" if len(covered_current) == len(current) else "PARTIAL"),
                },
                "research_evidence": deepcopy(research_by_id.get(internal_id)),
            }
        if internal_id == "COMBINED_PORTFOLIO" and strategy_history:
            strategy_record.update(
                {
                    "data_status": "DERIVED_COMPLETE",
                    "data_state": "DERIVED_COMPLETE",
                    "current_operational_status": "RECONSTRUCTED_PAPER_BACKFILL",
                    "current_operational_label": "Derived Combined Strategy Ledger",
                    "operational_data_source": "ordinary strategy operational daily ledgers",
                    "execution_type": "Derived Combined Strategy Ledger",
                    "separate_combined_trade_ledger": None,
                    "separate_combined_paper_fills": False,
                    "cost_double_count": False,
                    "daily_cost": None,
                    "cumulative_cost": None,
                    "cost_treatment": strategy_history[-1].get("cost_treatment"),
                }
            )
        if internal_id == wq_gate["strategy_id"]:
            strategy_record["admission_gate"] = deepcopy(wq_gate)
            strategy_record["exact_blocker"] = wq_gate["exact_blocker"]
            strategy_record["proposed_post_admission_sleeve_weight"] = 1 / PENDING_POST_ADMISSION_SLEEVES
        strategies.append(strategy_record)
        strategies[-1]["max_drawdown"] = _max_drawdown(
            [{"current_drawdown": row.get("current_drawdown")} for row in strategy_history]
        )

    top_contributors, top_detractors = _official_contributors(strategies)
    official_close_dates = sorted({row.get("official_close_date") for row in portfolio_daily if row.get("official_close_date")})
    expected_official_close = canonical["portfolio_summary"].get("as_of_date")
    missing_official_dates = (
        [expected_official_close]
        if expected_official_close and expected_official_close not in official_close_dates else []
    )
    official_blocker = (
        "Missing Official Daily Record: no portfolio_daily row has data_as_of/return_end_date "
        f"{expected_official_close}."
        if missing_official_dates else None
    )
    effective_by_id = {row["internal_id"]: row.get("strategy_effective_date") for row in strategies}
    strategy_daily = [
        row for row in strategy_daily
        if not effective_by_id.get(row["strategy_id"])
        or row.get("date") >= effective_by_id[row["strategy_id"]]
    ]
    entity_inventory = _entity_inventory(strategies, history_by_id, trade_by_id, holding_by_id)
    latest = portfolio_daily[-1] if portfolio_daily else {}
    official = {
        "accounting_label": "OFFICIAL_DAILY",
        "immutable_after_reconciliation": True,
        "nav": latest.get("ending_nav"),
        "daily_gross_pnl": latest.get("gross_pnl"),
        "daily_transaction_cost": latest.get("transaction_cost"),
        "daily_net_pnl": latest.get("net_pnl"),
        "cumulative_gross_pnl": sum(float(row.get("gross_pnl") or 0) for row in portfolio_daily),
        "cumulative_transaction_costs": sum(float(row.get("transaction_cost") or 0) for row in portfolio_daily),
        "cumulative_net_pnl": latest.get("cumulative_pnl"),
        "operating_period_return": latest.get("cumulative_return"),
        "current_drawdown": latest.get("current_drawdown"),
        "max_drawdown": _max_drawdown(portfolio_daily),
        "as_of": canonical["portfolio_summary"].get("as_of_date"),
        "latest_official_close_date": official_close_dates[-1] if official_close_dates else None,
        "record_count": len(portfolio_daily),
        "missing_dates": missing_official_dates,
        "blocker": official_blocker,
    }
    intraday_estimate = {
        "accounting_label": "INTRADAY_ESTIMATE",
        "provider": (intraday or {}).get("provider"),
        "price_source_label": "Delayed Market Price" if intraday else None,
        "nav_label": "Intraday Estimated NAV" if intraday else None,
        "pnl_label": "Intraday Estimated P&L" if intraday else None,
        "provider_classification": "DELAYED_FREE_MARKET_DATA" if intraday else None,
        "estimated_nav": (intraday or {}).get("estimated_nav"),
        "estimated_pnl": (intraday or {}).get("estimated_pnl"),
        "market_data_as_of": (intraday or {}).get("market_data_as_of"),
        "covered_tickers": (intraday or {}).get("covered_tickers"),
        "total_tickers": (intraday or {}).get("total_tickers"),
        "missing_tickers": (intraday or {}).get("missing_tickers"),
        "stale_tickers": (intraday or {}).get("stale_tickers"),
        "residual_pnl": (intraday or {}).get("residual_pnl"),
        "written_to_official_ledger": False,
    }
    refresh_meta = (intraday or {}).get("refresh_meta") or {}
    decision_rows = decisions or []
    portfolio_summary = deepcopy(canonical["portfolio_summary"])
    portfolio_summary.update(
        {
            "reconstructed_portfolio_start_date": portfolio_dates["reconstructed_portfolio_start_date"],
            "verified_shadow_portfolio_start_date": portfolio_dates["verified_shadow_portfolio_start_date"],
            "verified_shadow_start_label": portfolio_dates["verified_shadow_portfolio_start_date"] or "Not Yet Established",
            "official_daily_nav": official["nav"],
            "official_daily_pnl": official["daily_net_pnl"],
            "intraday_estimated_nav": intraday_estimate["estimated_nav"],
            "intraday_estimated_pnl": intraday_estimate["estimated_pnl"],
            "cumulative_gross_pnl": official["cumulative_gross_pnl"],
            "cumulative_transaction_costs": official["cumulative_transaction_costs"],
            "cumulative_net_pnl": official["cumulative_net_pnl"],
            "operating_period_return": official["operating_period_return"],
            "operating_period_current_drawdown": official["current_drawdown"],
            "operating_period_max_drawdown": official["max_drawdown"],
            "gross_exposure": latest.get("gross_exposure"),
            "net_exposure": latest.get("net_exposure"),
            "long_exposure": latest.get("long_exposure"),
            "short_exposure": latest.get("short_exposure"),
        }
    )
    held_tickers = sorted({row["ticker"] for row in holdings})
    raw_latest_by_id = {}
    for row in raw_strategy_daily:
        raw_latest_by_id[row["strategy_id"]] = row
    strategy_daily_pnl = sum(float(row["daily_pnl"]) for row in raw_latest_by_id.values() if row.get("daily_pnl") is not None)
    strategy_cumulative_pnl = sum(float(row["cumulative_pnl"]) for row in raw_latest_by_id.values() if row.get("cumulative_pnl") is not None)
    trade_cost_total = sum(float(row["total_cost"]) for row in trades if row.get("total_cost") is not None)
    strategy_cost_total = sum(float(row["transaction_cost"]) for row in raw_strategy_daily if row.get("transaction_cost") is not None)
    strategy_cost_reconciliation = {}
    for strategy in strategies:
        strategy_id = strategy["internal_id"]
        selected_trades = trade_by_id.get(strategy_id, [])
        selected_history = [
            row for row in history_by_id.get(strategy_id, [])
            if not strategy.get("strategy_effective_date")
            or row.get("date") >= strategy["strategy_effective_date"]
        ]
        trade_total = sum(float(row.get("total_cost") or 0) for row in selected_trades)
        ledger_total = sum(float(row.get("transaction_cost") or 0) for row in selected_history)
        strategy_cost_reconciliation[strategy_id] = {
            "status": "RECONCILED" if abs(trade_total - ledger_total) <= 1e-8 else "REVIEW_REQUIRED",
            "selected_strategy_trade_rows": len(selected_trades),
            "selected_strategy_trade_row_cost": trade_total,
            "selected_strategy_daily_cost": strategy.get("daily_cost"),
            "selected_strategy_cumulative_cost": ledger_total,
            "portfolio_trade_rows": len(trades),
            "portfolio_cumulative_cost": official["cumulative_transaction_costs"],
            "reconciliation_residual": trade_total - ledger_total,
        }
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id or f"ops-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
        "generated_at": generated,
        "refresh_status": refresh_status,
        "data_freshness": refresh_meta.get("data_freshness") or ("DELAYED" if intraday else "OFFICIAL_CLOSE"),
        "market_session_status": refresh_meta.get("market_session_status"),
        "market_data_as_of": intraday_estimate["market_data_as_of"],
        "portfolio_valuation_as_of": official["as_of"],
        "official_strategy_signal_as_of": canonical["operational_status"].get("latest_valid_target_position_date"),
        "latest_execution_as_of": canonical["operational_status"].get("latest_simulated_execution_date"),
        "last_successful_refresh": refresh_meta.get("last_successful_refresh"),
        "next_refresh": refresh_meta.get("next_refresh"),
        "portfolio_summary": portfolio_summary,
        "official_daily": official,
        "intraday_estimate": intraday_estimate,
        "membership_timeline": deepcopy(canonical["membership_timeline"]),
        "reconciliation_status": canonical["portfolio_summary"].get("data_status"),
        "strategies": strategies,
        "strategy_display_metadata": metadata,
        "holdings": published_holdings,
        "strategy_contribution": [
            {
                "internal_id": row["internal_id"],
                "official_daily_pnl": row.get("daily_pnl"),
                "estimated_daily_pnl": row.get("estimated_daily_pnl"),
                "daily_pnl": row.get("estimated_daily_pnl") if row.get("estimated_daily_pnl") is not None else row.get("daily_pnl"),
            }
            for row in strategies
        ],
        "ticker_security_contribution": (intraday or {}).get("ticker_security_contribution") or [],
        "top_contributors": top_contributors,
        "top_detractors": top_detractors,
        "trades": trades,
        "alerts": deepcopy(canonical["alerts"]),
        "proposal_state": _proposal_state(strategies, portfolio_summary, decision_rows),
        "decisions": decision_rows,
        "available_factor_outputs": None,
        "available_correlation_outputs": deepcopy(canonical["operational_status"].get("correlation")),
        "portfolio_daily": portfolio_daily,
        "strategy_daily": strategy_daily,
        "initial_execution_validation": {
            "status": "RECONSTRUCTED_PAPER_BACKFILL",
            "signal_as_of_date": None,
            "required_signal_as_of_date": "2026-06-03",
            "signal_generated_at": None,
            "data_cutoff": None,
            "target_effective_date": "2026-06-04",
            "execution_date": "2026-06-04",
            "execution_convention": "RETROSPECTIVE_PAPER_BACKFILL",
            "execution_price_source": None,
            "reference_price": None,
            "quantity": None,
            "notional": None,
            "transaction_cost": None,
            "blocker": "Initial record is a Reconstructed Paper Record / Retrospective Paper Backfill with blank signal_date and no initial trade/reference-price artifact.",
        },
        "execution_provenance": {
            "allowed_states": sorted(PROVENANCE_STATES),
            "strategy_record_counts": {
                state: sum(row.get("execution_provenance") == state for row in strategy_daily)
                for state in sorted(PROVENANCE_STATES)
            },
            "portfolio_record_counts": {
                state: sum(row.get("execution_provenance") == state for row in portfolio_daily)
                for state in sorted(PROVENANCE_STATES)
            },
            "trade_record_counts": {
                state: sum(row.get("execution_provenance") == state for row in trades)
                for state in sorted(PROVENANCE_STATES)
            },
        },
        "wq_admission_gate": wq_gate,
        "portfolio_dates": portfolio_dates,
        "capital_reconciliation": {
            "initial_shadow_capital": INITIAL_SHADOW_CAPITAL,
            "top_level_active_sleeves": TOP_LEVEL_ACTIVE_SLEEVES,
            "top_level_sleeve_weight": 1 / TOP_LEVEL_ACTIVE_SLEEVES,
            "starting_capital_per_sleeve": INITIAL_SLEEVE_CAPITAL,
            "combined_internal_constituents": len(combined_member_ids),
            "combined_internal_weight": 1 / len(combined_member_ids) if combined_member_ids else None,
            "combined_starting_capital": INITIAL_SLEEVE_CAPITAL,
            "expected_ordinary_active_sleeves": EXPECTED_ORDINARY_ACTIVE_SLEEVES,
            "ordinary_operational_ledgers": entity_inventory["ordinary_operational_ledgers"],
            "pending_post_admission_sleeves": PENDING_POST_ADMISSION_SLEEVES,
            "pending_post_admission_sleeve_weight": 1 / PENDING_POST_ADMISSION_SLEEVES,
            "portfolio_ending_nav": official["nav"],
            "portfolio_residual": None,
            "basis": "Top-level strategy analytics use the 17 current active sleeves: 16 ordinary active strategies plus the active Combined strategy. WQ_ALPHA_018 remains pending #000018.",
        },
        "strategy_entity_inventory": entity_inventory,
        "strategy_cost_reconciliation": strategy_cost_reconciliation,
        "operational_status": deepcopy(canonical["operational_status"]),
        "pending_membership": deepcopy(canonical["pending_membership"][0]) if canonical["pending_membership"] else None,
        "operational_universe": {
            "held_ticker_count": len(held_tickers),
            "current_price_covered_ticker_count": intraday_estimate["covered_tickers"],
            "operational_pricing_universe_size": operational_pricing_universe_size,
            "held_ticker_coverage_scope": "Current date-effective holdings only",
            "pricing_universe_scope": "Full operational pricing universe",
        },
        "strategy_reconciliation": {
            "daily_strategy_pnl_sum": strategy_daily_pnl,
            "master_portfolio_daily_pnl": official["daily_net_pnl"],
            "daily_pnl_residual": (
                official["daily_net_pnl"] - strategy_daily_pnl
                if official["daily_net_pnl"] is not None else None
            ),
            "cumulative_strategy_pnl_sum": strategy_cumulative_pnl,
            "master_portfolio_cumulative_pnl": official["cumulative_net_pnl"],
            "cumulative_pnl_residual": (
                official["cumulative_net_pnl"] - strategy_cumulative_pnl
                if official["cumulative_net_pnl"] is not None else None
            ),
        },
        "cost_reconciliation": {
            "trade_row_count": len(trades),
            "trade_row_total": trade_cost_total,
            "strategy_daily_total": strategy_cost_total,
            "portfolio_daily_total": official["cumulative_transaction_costs"],
            "trade_to_strategy_residual": trade_cost_total - strategy_cost_total,
            "trade_to_portfolio_residual": trade_cost_total - official["cumulative_transaction_costs"],
            "tolerance": 1e-8,
            "excluded_rows": 0,
            "status": "RECONCILED" if (
                abs(trade_cost_total - strategy_cost_total) <= 1e-8
                and abs(trade_cost_total - official["cumulative_transaction_costs"]) <= 1e-8
            ) else "REVIEW_REQUIRED",
        },
    }


def load_or_build_operational_snapshot(root: Path) -> dict[str, Any]:
    paths = _paths(root)
    existing = {}
    if paths["snapshot"].exists():
        existing = _read_json(paths["snapshot"], {})
        if (
            existing.get("snapshot_version") == SNAPSHOT_VERSION
            and existing.get("capital_reconciliation")
            and (not _research_mapping_available(root) or _snapshot_research_evidence(existing))
        ):
            return existing
    canonical = _read_json(paths["canonical"], {})
    source = _read_json(paths["source_bundle"], {}).get("shadow_live", {})
    research = load_strategy_research_artifacts(root, canonical["strategies"])
    snapshot = build_operational_snapshot(
        canonical,
        intraday={
            "provider": existing.get("intraday_estimate", {}).get("provider"),
            "estimated_nav": existing.get("intraday_estimate", {}).get("estimated_nav"),
            "estimated_pnl": existing.get("intraday_estimate", {}).get("estimated_pnl"),
            "market_data_as_of": existing.get("intraday_estimate", {}).get("market_data_as_of"),
            "covered_tickers": existing.get("intraday_estimate", {}).get("covered_tickers"),
            "missing_tickers": existing.get("intraday_estimate", {}).get("missing_tickers"),
            "stale_tickers": existing.get("intraday_estimate", {}).get("stale_tickers"),
            "residual_pnl": existing.get("intraday_estimate", {}).get("residual_pnl"),
            "holdings": existing.get("holdings"),
            "strategy_contribution": {
                row["internal_id"]: row.get("intraday_estimated_pnl")
                for row in existing.get("strategies", [])
            },
            "ticker_security_contribution": existing.get("ticker_security_contribution"),
            "refresh_meta": {
                "data_freshness": existing.get("data_freshness"),
                "market_session_status": existing.get("market_session_status"),
                "last_successful_refresh": existing.get("last_successful_refresh"),
                "next_refresh": existing.get("next_refresh"),
            },
        } if existing.get("intraday_estimate", {}).get("provider") else None,
        decisions=read_decisions(root),
        operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
        strategy_research_details=research,
    )
    _atomic_write_json(paths["snapshot"], snapshot)
    return snapshot


def _research_mapping_available(root: Path) -> bool:
    return (root / "data/config/strategy_research_mapping.json").exists()


def _snapshot_research_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        row["internal_id"]: row["research_evidence"]
        for row in snapshot.get("strategies", [])
        if row.get("internal_id") and row.get("research_evidence")
    }


def refresh_operational_snapshot(
    root: Path,
    *,
    fetch_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh delayed intraday estimates and atomically publish a last-known-good snapshot."""
    paths = _paths(root)
    with snapshot_refresh_lock(paths["lock"]) as acquired:
        if not acquired:
            return {"ok": False, "refresh_status": "REFRESHING", "error": "refresh_already_in_progress"}
        prior = load_or_build_operational_snapshot(root)
        try:
            canonical = _read_json(paths["canonical"], {})
            source = _read_json(paths["source_bundle"], {}).get("shadow_live", {})
            holdings = _current_holdings(canonical["holdings"])
            tickers = sorted({row["ticker"] for row in holdings})
            fetcher = fetch_fn or fetch_intraday_bars
            fetched = fetcher(tickers, bar_interval="5m", refresh_interval_minutes=5)
            bars = latest_bar_by_ticker(fetched.get("rows") or [])
            if not bars:
                raise ValueError("delayed price refresh returned zero priced holdings")
            enriched_holdings = []
            strategy_contribution: dict[str, float] = {}
            ticker_contribution: dict[str, float] = {}
            missing = set(fetched.get("missing_tickers") or [])
            stale = set(fetched.get("stale_tickers") or [])
            latest_price_as_of = fetched.get("latest_completed_bar_ts_et") or fetched.get("latest_observation_ts_et")
            for row in holdings:
                bar = bars.get(row["ticker"])
                price_change = bar.get("intraday_return_from_open") if bar else None
                pnl = float(row["simulated_notional"]) * float(price_change) if price_change is not None else None
                enriched_holdings.append(
                    {
                        **row,
                        "side": "LONG" if float(row["target_weight"]) > 0 else "SHORT",
                        "latest_price": bar.get("close") if bar else None,
                        "latest_price_source": "Delayed Market Price" if bar else None,
                        "latest_delayed_price_as_of": bar.get("observation_ts_et") if bar else None,
                        "data_as_of": latest_price_as_of if bar else None,
                        "price_change": price_change,
                        "daily_estimated_pnl": pnl,
                        "estimated_contribution": pnl,
                    }
                )
                if pnl is not None:
                    strategy_contribution[row["strategy_id"]] = strategy_contribution.get(row["strategy_id"], 0.0) + pnl
                    ticker_contribution[row["ticker"]] = ticker_contribution.get(row["ticker"], 0.0) + pnl
            estimated_pnl = sum(strategy_contribution.values()) if strategy_contribution else None
            official_nav = canonical["portfolio_summary"].get("nav")
            now = datetime.now(timezone.utc)
            session = market_session_status(interval_minutes=5)
            priced_tickers = len(bars)
            freshness = "STALE" if missing or stale or priced_tickers < len(tickers) else "DELAYED"
            intraday = {
                "provider": fetched.get("provider") or "yfinance",
                "estimated_nav": official_nav + estimated_pnl if official_nav is not None and estimated_pnl is not None else None,
                "estimated_pnl": estimated_pnl,
                "market_data_as_of": latest_price_as_of,
                "covered_tickers": priced_tickers,
                "total_tickers": len(tickers),
                "missing_tickers": sorted(missing),
                "stale_tickers": sorted(stale),
                "residual_pnl": None if not missing else None,
                "holdings": enriched_holdings,
                "strategy_contribution": strategy_contribution,
                "ticker_security_contribution": [
                    {"ticker": ticker, "daily_estimated_pnl": pnl}
                    for ticker, pnl in sorted(ticker_contribution.items(), key=lambda item: abs(item[1]), reverse=True)
                ],
                "refresh_meta": {
                    "data_freshness": freshness,
                    "market_session_status": session.status,
                    "last_successful_refresh": now.isoformat(),
                    "next_refresh": (now + timedelta(seconds=REFRESH_INTERVAL_SECONDS)).isoformat(),
                },
            }
            snapshot = build_operational_snapshot(
                canonical,
                intraday=intraday,
                decisions=read_decisions(root),
                operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
                strategy_research_details=_snapshot_research_evidence(prior),
                refresh_status="SUCCESS" if freshness == "DELAYED" else "STALE",
            )
            _atomic_write_json(paths["snapshot"], snapshot)
            _atomic_write_json(paths["status"], {"state": snapshot["refresh_status"], "snapshot_id": snapshot["snapshot_id"], "at": now.isoformat()})
            return {"ok": True, **snapshot}
        except Exception as exc:
            failed_at = datetime.now(timezone.utc).isoformat()
            stale_snapshot = deepcopy(prior) if prior else {}
            if stale_snapshot:
                stale_snapshot["refresh_status"] = "STALE"
                stale_snapshot["data_freshness"] = "STALE"
                stale_snapshot["last_failed_refresh"] = failed_at
                stale_snapshot["refresh_error"] = str(exc)
                stale_snapshot["alerts"] = list(stale_snapshot.get("alerts") or []) + [
                    {
                        "severity": "HIGH",
                        "title": "Delayed price refresh failed",
                        "detail": str(exc),
                    }
                ]
                _atomic_write_json(paths["snapshot"], stale_snapshot)
            _atomic_write_json(
                paths["status"],
                {"state": "FAILED", "snapshot_id": prior.get("snapshot_id"), "failed_at": failed_at, "error": str(exc)},
            )
            return {
                "ok": False,
                "refresh_status": "STALE" if prior else "FAILED",
                "snapshot_id": prior.get("snapshot_id"),
                "generated_at": prior.get("generated_at"),
                "error": str(exc),
            }


def read_decisions(root: Path) -> list[dict[str, Any]]:
    return _read_json(_paths(root)["decisions"], [])


def persist_decision(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "").upper()
    if action not in {"APPROVE", "REJECT", "MODIFY"}:
        raise ValueError("action must be APPROVE, REJECT, or MODIFY")
    reviewer = str(payload.get("reviewer") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    if not reviewer or not rationale:
        raise ValueError("reviewer and rationale are required")
    canonical = _read_json(_paths(root)["canonical"], {})
    accepted = {row["internal_id"] for row in canonical["strategies"]}
    previous = load_or_build_operational_snapshot(root).get("proposal_state", {}).get("proposed_weights") or {}
    proposed = payload.get("new_proposed_weights") if action == "MODIFY" else previous
    if action == "MODIFY":
        if not isinstance(proposed, dict) or not proposed:
            raise ValueError("new_proposed_weights required for MODIFY")
        if set(proposed) - accepted:
            raise ValueError("only accepted strategies may receive allocation")
        if any(float(value) < 0 for value in proposed.values()):
            raise ValueError("weights cannot be negative")
        total = sum(float(value) for value in proposed.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError("weights must normalize to 100%")
    turnover = sum(abs(float(proposed.get(key, 0)) - float(previous.get(key, 0))) for key in accepted) / 2
    decision = {
        "decision_id": f"decision-{uuid4().hex[:12]}",
        "scope": payload.get("scope") or "portfolio",
        "previous_proposal": previous,
        "new_proposed_weights": proposed,
        "action": action,
        "reviewer": reviewer,
        "rationale": rationale,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proposed_effective_date": payload.get("proposed_effective_date"),
        "status": "RECORDED",
        "estimated_turnover": turnover,
        "estimated_cost": turnover * float(canonical["portfolio_summary"].get("nav") or 0) * 0.0005,
        "execution_authorized": False,
        "environment": str(payload.get("environment") or "OPERATIONAL").upper(),
    }
    decisions = read_decisions(root)
    decisions.append(decision)
    _atomic_write_json(_paths(root)["decisions"], decisions)
    prior = load_or_build_operational_snapshot(root)
    source = _read_json(_paths(root)["source_bundle"], {}).get("shadow_live", {})
    snapshot = build_operational_snapshot(
        canonical,
        intraday={
            "provider": prior.get("intraday_estimate", {}).get("provider"),
            "estimated_nav": prior.get("intraday_estimate", {}).get("estimated_nav"),
            "estimated_pnl": prior.get("intraday_estimate", {}).get("estimated_pnl"),
            "market_data_as_of": prior.get("market_data_as_of"),
            "covered_tickers": prior.get("intraday_estimate", {}).get("covered_tickers"),
            "missing_tickers": prior.get("intraday_estimate", {}).get("missing_tickers"),
            "residual_pnl": prior.get("intraday_estimate", {}).get("residual_pnl"),
            "holdings": prior.get("holdings"),
            "strategy_contribution": {
                row["internal_id"]: row.get("intraday_estimated_pnl")
                for row in prior.get("strategies", [])
            },
            "ticker_security_contribution": prior.get("ticker_security_contribution"),
            "refresh_meta": {
                "data_freshness": prior.get("data_freshness"),
                "market_session_status": prior.get("market_session_status"),
                "last_successful_refresh": prior.get("last_successful_refresh"),
                "next_refresh": prior.get("next_refresh"),
            },
        } if prior.get("intraday_estimate", {}).get("provider") else None,
        decisions=decisions,
        operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
        strategy_research_details=_snapshot_research_evidence(prior),
        refresh_status="DECISION_RECORDED",
    )
    _atomic_write_json(_paths(root)["snapshot"], snapshot)
    return decision
