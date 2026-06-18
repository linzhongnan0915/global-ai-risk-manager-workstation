"""Versioned operational snapshot and local decision audit for Command Center."""

from __future__ import annotations

import json
import math
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from src.market.intraday_provider import fetch_intraday_bars, latest_bar_by_ticker
from src.market.market_hours import market_session_status
from src.market.paper_portfolio_ledger import paper_portfolio_snapshot_payload, upsert_paper_portfolio_daily
from src.reporting.strategy_research_artifacts import load_strategy_research_artifacts
from src.strategies.display_metadata import strategy_display_metadata


SNAPSHOT_VERSION = "3.6.7"
MARKET_PROXY_MIN_OBSERVATIONS = 20
MARKET_PROXY_DISCLOSURE = (
    "Market Data Proxy; Delayed yfinance overlay where cached in operational artifacts; "
    "Not a validated Barra / institutional factor model; Not live brokerage; "
    "Not live real-time market data."
)
REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS = {"WQ_ALPHA_018"}
INTRADAY_OVERLAY_SCHEMA_VERSION = "intraday_overlay_v1"
INTRADAY_OVERLAY_STALE_AFTER_SECONDS = 10 * 60
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
    "INVALID_EXECUTION_RECORD": "Paper Provenance Pending",
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
        "market_proxy_cache": root / "dashboard/data/risk_factor_market_proxy_cache.json",
        "sp500_reference_universe": root / "dashboard/data/universes/sp500_current.json",
        "snapshot": root / "output/operational_snapshot.json",
        "intraday_overlay": root / "output/operational_intraday_overlay.json",
        "status": root / "output/operational_refresh_status.json",
        "lock": root / "output/operational_snapshot.lock",
        "decisions": root / "output/command_center_decisions.json",
    }


def _sp500_reference_universe_payload(universe: dict[str, Any] | None) -> dict[str, Any]:
    if not universe:
        return {
            "status": "NOT_LOADED",
            "artifact_path": "dashboard/data/universes/sp500_current.json",
            "description": "Current S&P 500 reference universe, not historical constituent-corrected.",
            "provider": None,
            "as_of_date": None,
            "constituent_count": 0,
            "current_constituent": True,
            "fields": ["ticker", "company_name", "sector", "industry", "market_cap", "source", "as_of_date", "provider", "current_constituent"],
            "constituents": [],
        }
    constituents = deepcopy(universe.get("constituents") or universe.get("rows") or [])
    normalized = []
    for row in constituents:
        normalized.append(
            {
                "ticker": row.get("ticker"),
                "company_name": row.get("company_name") or row.get("name"),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "market_cap": row.get("market_cap"),
                "source": row.get("source") or universe.get("source"),
                "as_of_date": row.get("as_of_date") or universe.get("as_of_date"),
                "provider": row.get("provider") or universe.get("provider"),
                "current_constituent": row.get("current_constituent", True),
            }
        )
    return {
        "status": "LOADED",
        "artifact_path": "dashboard/data/universes/sp500_current.json",
        "description": "Current S&P 500 reference universe, not historical constituent-corrected.",
        "provider": universe.get("provider"),
        "as_of_date": universe.get("as_of_date"),
        "constituent_count": len(normalized),
        "current_constituent": True,
        "fields": ["ticker", "company_name", "sector", "industry", "market_cap", "source", "as_of_date", "provider", "current_constituent"],
        "constituents": normalized,
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


def _date_from_iso(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:10]


def _trading_session_lifecycle(
    *,
    portfolio_daily: list[dict[str, Any]],
    strategy_daily: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    official: dict[str, Any],
    intraday_estimate: dict[str, Any],
    refresh_meta: dict[str, Any],
) -> dict[str, Any]:
    """Classify delayed estimates without promoting them into official NEXT_OPEN_TO_OPEN records."""
    latest_official_ledger_date = portfolio_daily[-1].get("date") if portfolio_daily else None
    official_dates = {row.get("date") for row in portfolio_daily if row.get("date")}
    delayed_as_of = intraday_estimate.get("market_data_as_of")
    current_session = refresh_meta.get("session_date") or _date_from_iso(delayed_as_of)
    has_estimate = (
        delayed_as_of is not None
        or intraday_estimate.get("estimated_nav") is not None
        or intraday_estimate.get("estimated_pnl") is not None
    )
    market_status = refresh_meta.get("market_session_status")
    official_promoted = bool(current_session and current_session in official_dates)
    blockers: list[str] = []
    if not has_estimate:
        state = "OFFICIAL_ONLY"
        blockers.append("No current delayed estimate is available for official promotion.")
    elif official_promoted:
        state = "OFFICIAL_PROMOTED"
    else:
        closed_status = str(market_status or "").lower() in {"after-hours", "closed", "post_close_pending"}
        state = "EOD_PENDING_OFFICIAL_PROMOTION" if closed_status else "INTRADAY_ESTIMATE"
        blockers.append("Official portfolio_daily row is not present for the current trading session.")
        blockers.append("NEXT_OPEN_TO_OPEN requires the next-open return endpoint; same-day close promotion would require a separate accounting decision.")
        ordinary_rows = [
            row for row in strategy_daily
            if row.get("date") == current_session and row.get("strategy_id") != "COMBINED_PORTFOLIO"
        ]
        if len({row.get("strategy_id") for row in ordinary_rows}) < EXPECTED_ORDINARY_ACTIVE_SLEEVES:
            blockers.append("Missing complete ordinary strategy daily rows for the current trading session.")
        if not any(row.get("execution_date") == current_session for row in trades):
            blockers.append("Missing paper fill rows for the current trading session.")
        if not any(row.get("date") == current_session for row in holdings):
            blockers.append("Missing position rows for the current trading session.")
        blockers.append("Target row detail is not loaded in the operational snapshot; verify canonical target snapshots before promotion.")
        blockers.append("Operational snapshot must be rebuilt after official ledger generation.")
    required_inputs = [
        {
            "input": "market data endpoint required by NEXT_OPEN_TO_OPEN",
            "status": "Complete" if official_promoted else ("Pending" if has_estimate else "Not loaded"),
        },
        {
            "input": "strategy daily rows",
            "status": "Complete" if current_session and any(row.get("date") == current_session for row in strategy_daily) else "Missing",
        },
        {
            "input": "target rows",
            "status": "Not loaded in operational snapshot",
        },
        {
            "input": "paper fill rows",
            "status": "Complete" if current_session and any(row.get("execution_date") == current_session for row in trades) else "Missing",
        },
        {
            "input": "position rows",
            "status": "Complete" if current_session and any(row.get("date") == current_session for row in holdings) else "Missing",
        },
        {
            "input": "Combined derived row",
            "status": "Derived complete" if current_session and any(
                row.get("date") == current_session and row.get("strategy_id") == "COMBINED_PORTFOLIO"
                for row in strategy_daily
            ) else "Derived unavailable",
        },
        {
            "input": "snapshot rebuild",
            "status": "Required after official generation" if not official_promoted else "Complete",
        },
    ]
    labels = {
        "OFFICIAL_ONLY": "Official only",
        "INTRADAY_ESTIMATE": "Intraday estimate / not official ledger",
        "EOD_PENDING_OFFICIAL_PROMOTION": "EOD estimate pending official ledger promotion",
        "OFFICIAL_PROMOTED": "Official promoted",
    }
    return {
        "state": state,
        "state_label": labels[state],
        "latest_official_ledger_date": latest_official_ledger_date,
        "official_close_as_of": official.get("latest_official_close_date"),
        "delayed_estimate_as_of": delayed_as_of,
        "current_trading_session_date": current_session,
        "market_session_status": market_status,
        "official_promotion_blockers": blockers,
        "required_inputs": required_inputs,
        "accounting_convention": "NEXT_OPEN_TO_OPEN",
        "promotion_condition": "Promotion requires a canonical portfolio_daily row generated from real NEXT_OPEN_TO_OPEN inputs; delayed estimates are never written to the official ledger.",
        "chart_behavior": "Official portfolio_daily.date records are solid; delayed estimates are dashed and excluded when the session is official-promoted.",
    }


def official_promotion_readiness(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic EOD promotion readiness without mutating official ledgers."""
    lifecycle = snapshot.get("trading_session_lifecycle") or {}
    state = lifecycle.get("state") or "OFFICIAL_ONLY"
    target_ledger_date = lifecycle.get("current_trading_session_date")
    blockers = list(lifecycle.get("official_promotion_blockers") or [])
    hard_blockers = [
        item for item in blockers
        if not str(item).startswith("Official portfolio_daily row is not present")
        and not str(item).startswith("Operational snapshot must be rebuilt")
    ]
    if state == "EOD_PENDING_OFFICIAL_PROMOTION" and not hard_blockers:
        readiness_state = "READY_FOR_PROMOTION"
        can_promote = True
    else:
        readiness_state = state
        can_promote = False
    if state == "OFFICIAL_PROMOTED":
        can_promote = False
    command = None
    if can_promote and target_ledger_date:
        command = (
            f"python scripts\\promote_eod_official_ledger.py --target-date {target_ledger_date} --dry-run"
        )
    return {
        "can_promote": can_promote,
        "readiness_state": readiness_state,
        "target_ledger_date": target_ledger_date,
        "required_return_endpoint": (
            f"next trading open after {target_ledger_date}"
            if target_ledger_date
            else "N/A"
        ),
        "accounting_convention": lifecycle.get("accounting_convention") or "NEXT_OPEN_TO_OPEN",
        "blockers": blockers if not can_promote else [],
        "input_blockers": hard_blockers,
        "recommended_command": command,
        "manual_dry_run_command": (
            f"python scripts\\promote_eod_official_ledger.py --target-date {target_ledger_date} --dry-run"
            if target_ledger_date
            else "N/A"
        ),
        "execute_enabled": False,
        "execute_mode": "Deferred in Step 13A; use dry-run readiness only.",
        "latest_official_ledger_date": lifecycle.get("latest_official_ledger_date"),
        "official_close_as_of": lifecycle.get("official_close_as_of"),
        "delayed_estimate_as_of": lifecycle.get("delayed_estimate_as_of"),
        "current_trading_session_date": target_ledger_date,
        "market_session_status": lifecycle.get("market_session_status"),
        "promotion_policy": (
            "Official promotion is manual and disabled by default. Under NEXT_OPEN_TO_OPEN, "
            "same-day close does not automatically create a same-day portfolio_daily.date."
        ),
        "required_pipeline": [
            "scripts\\run_shadow_live_daily.py with the correct raw_end_date",
            "scripts\\build_canonical_frontend_contract.py",
            "scripts\\build_operational_snapshot.py",
        ],
    }


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
    if not evidence["canonical_signal_date"]:
        blockers.append("Missing canonical signal date")
    if evidence["canonical_target_rows"] == 0:
        blockers.append("Missing target rows")
    if evidence["canonical_trade_rows"] == 0:
        blockers.append("Missing paper fill rows")
    if evidence["canonical_position_rows"] == 0:
        blockers.append("Missing position rows")
    if evidence["verified_execution_rows"] == 0:
        blockers.append("Missing verified execution provenance")
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


FACTOR_COLUMNS = (
    "market",
    "size",
    "value",
    "momentum",
    "quality",
    "volatility",
    "liquidity",
)


def _missing_factor_value(value: Any) -> Any:
    if value is None or value == "":
        return "Missing Metadata"
    return value


def _sleeve_type(strategy: dict[str, Any]) -> str:
    if strategy.get("internal_id") == "COMBINED_PORTFOLIO":
        return "Composite"
    if strategy.get("membership_state") == "approved_pending":
        return "Pending"
    if strategy.get("repair_state"):
        return "Repair"
    if strategy.get("reference_only"):
        return "Reference"
    return "Alpha Strategy"


def _primary_status(strategy: dict[str, Any]) -> str:
    if strategy.get("membership_state") == "approved_pending" or strategy.get("internal_id") == "WQ_ALPHA_018":
        return "APPROVED_PENDING / PRE_OPERATIONAL"
    if strategy.get("internal_id") == "COMBINED_PORTFOLIO":
        return "Active Composite"
    if strategy.get("membership_state") == "executed":
        return "Active Paper"
    return strategy.get("current_operational_label") or strategy.get("current_operational_status") or "N/A"


def _evidence_source(strategy: dict[str, Any]) -> str:
    evidence = strategy.get("research_evidence") or {}
    return (
        evidence.get("evidence_artifact")
        or strategy.get("evidence_reference")
        or strategy.get("formula_module")
        or "Not Available"
    )


def _missing_warning(strategy: dict[str, Any], factor_summary: dict[str, Any]) -> str:
    warnings = []
    if all(factor_summary.get(column) in {None, "", "Missing Metadata"} for column in FACTOR_COLUMNS):
        warnings.append("Factor metadata missing")
    if strategy.get("membership_state") == "approved_pending":
        warnings.append("Data Pending")
        blocker = strategy.get("exact_blocker")
        if blocker:
            warnings.append(blocker)
    if strategy.get("observation_count", 0) < 20 and strategy.get("membership_state") != "approved_pending":
        warnings.append("Insufficient History")
    return " | ".join(warnings) if warnings else "N/A"


def _safe_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _strategy_return_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in sorted(rows, key=lambda item: item.get("date") or ""):
        value = _safe_number(row.get("net_return") if row.get("net_return") is not None else row.get("daily_return"))
        if value is not None:
            output.append({"date": row.get("date"), "return": value})
    return output


def _annualized_realized_vol(return_rows: list[dict[str, Any]], window: int) -> float | str:
    if len(return_rows) < window:
        return "Insufficient History"
    values = [row["return"] for row in return_rows[-window:]]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def _market_proxy_cache(canonical: dict[str, Any], market_proxy_cache: dict[str, Any] | None) -> dict[str, Any]:
    return deepcopy(market_proxy_cache or canonical.get("risk_factor_market_proxy_cache") or {})


def _benchmark_returns_by_date(canonical: dict[str, Any], market_proxy_cache: dict[str, Any] | None = None) -> dict[str, float]:
    candidates = []
    cache = _market_proxy_cache(canonical, market_proxy_cache)
    benchmark = cache.get("benchmark") or {}
    if isinstance(benchmark.get("return_series"), list):
        candidates.extend(benchmark["return_series"])
    if isinstance(benchmark.get("daily_returns"), list):
        candidates.extend(benchmark["daily_returns"])
    if isinstance(benchmark.get("daily_returns"), dict):
        for date, value in benchmark["daily_returns"].items():
            candidates.append({"date": date, "return": value, "ticker": benchmark.get("symbol") or "SPY"})
    for key in (
        "benchmark_daily",
        "market_benchmark_daily",
        "spy_daily",
        "spy_price_history",
        "market_price_history",
    ):
        value = canonical.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    output: dict[str, float] = {}
    for row in candidates:
        ticker = str(row.get("ticker") or row.get("symbol") or row.get("benchmark") or "SPY").upper()
        if ticker != "SPY":
            continue
        date = row.get("date")
        value = _safe_number(row.get("return") if row.get("return") is not None else row.get("daily_return"))
        if date and value is not None:
            output[date] = value
    return output


def _compounded_return(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    compounded = 1.0
    for value in values[-window:]:
        compounded *= 1.0 + value
    return compounded - 1.0


def _annualized_return_volatility(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    sample = values[-window:]
    if len(sample) < 2:
        return None
    mean = sum(sample) / len(sample)
    variance = sum((value - mean) ** 2 for value in sample) / (len(sample) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def _current_drawdown_from_returns(values: list[float]) -> float | None:
    if not values:
        return None
    equity = 1.0
    peak = 1.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
    return equity / peak - 1.0 if peak else None


def _benchmark_reference_payload(
    canonical: dict[str, Any],
    market_proxy_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache = _market_proxy_cache(canonical, market_proxy_cache)
    benchmark = cache.get("benchmark") or {}
    metadata = cache.get("metadata") or {}
    returns_by_date = _benchmark_returns_by_date(canonical, cache)
    ordered = [
        {"date": date, "return": returns_by_date[date]}
        for date in sorted(returns_by_date)
    ]
    values = [row["return"] for row in ordered]
    latest_date = ordered[-1]["date"] if ordered else benchmark.get("latest_date")
    return {
        "benchmark_symbol": benchmark.get("symbol") or metadata.get("benchmark_symbol") or "SPY",
        "delayed_market_data": bool(metadata.get("delayed_market_data", True)),
        "not_live_market_data": bool(metadata.get("not_live_market_data", True)),
        "not_validated_institutional_factor_model": True,
        "observations": len(values),
        "return_20d": _compounded_return(values, 20),
        "return_63d": _compounded_return(values, 63),
        "volatility_20d": _annualized_return_volatility(values, 20),
        "volatility_63d": _annualized_return_volatility(values, 63),
        "current_drawdown": _current_drawdown_from_returns(values),
        "latest_date": latest_date,
        "source": "dashboard/data/risk_factor_market_proxy_cache.json" if cache else "Not Loaded",
        "provider": metadata.get("provider"),
        "status": "LOADED" if len(values) >= MARKET_PROXY_MIN_OBSERVATIONS else "NOT_LOADED",
        "description": "Delayed SPY benchmark proxy from cached market data; not live market data.",
    }


def _risk_factor_contract_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    visible = [
        row for row in rows
        if row.get("primary_status") != "APPROVED_PENDING / PRE_OPERATIONAL"
        and row.get("strategy_id") not in REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS
    ]
    pending = [
        row for row in rows
        if row.get("primary_status") == "APPROVED_PENDING / PRE_OPERATIONAL"
        and row.get("strategy_id") not in REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS
    ]
    return {
        "visible_active_strategy_count": len(visible),
        "pending_excluded_count": len(pending),
        "default_matrix_excludes": [],
        "pending_excluded_strategy_ids": [row.get("strategy_id") for row in pending if row.get("strategy_id")],
        "removed_from_current_workstation_strategy_ids": sorted(REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS),
        "default_matrix_columns": [
            "Strategy",
            "Status",
            "Weight",
            "Sharpe",
            "Ann Ret",
            "Max DD",
            "Beta",
            "Corr",
            "Vol",
            "Curr DD",
            "Mom20",
            "Mom63",
            "Liquidity",
            "Top Hold",
            "Top5",
            "Family",
            "Quality",
        ],
        "basis": (
            "Default Risk Factors matrix renders active rows from risk_factor_market_proxy_table; "
            "removed non-operating research candidates are not displayed as active, pending, or excluded."
        ),
    }


def _research_summary_payload(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    combined = next((row for row in strategies if row.get("internal_id") == "COMBINED_PORTFOLIO"), {})
    combined_metrics = (combined.get("research_evidence") or {}).get("research_metrics") or {}
    active_metrics = []
    for strategy in strategies:
        if strategy.get("internal_id") in {"COMBINED_PORTFOLIO", "WQ_ALPHA_018"}:
            continue
        if strategy.get("operational_state") == "PRE_OPERATIONAL":
            continue
        metrics = (strategy.get("research_evidence") or {}).get("research_metrics") or {}
        if metrics:
            active_metrics.append(metrics)
    sharpes = [value for value in (_safe_number(row.get("net_sharpe")) for row in active_metrics) if value is not None]
    drawdowns = [value for value in (_safe_number(row.get("max_drawdown")) for row in active_metrics) if value is not None]
    active_avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else None
    active_median_sharpe = None
    if sharpes:
        ordered = sorted(sharpes)
        middle = len(ordered) // 2
        active_median_sharpe = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "combined_sharpe_available": _safe_number(combined_metrics.get("net_sharpe")) is not None,
        "combined_mdd_available": _safe_number(combined_metrics.get("max_drawdown")) is not None,
        "combined_sharpe": _safe_number(combined_metrics.get("net_sharpe")),
        "combined_max_drawdown": _safe_number(combined_metrics.get("max_drawdown")),
        "active_strategy_metrics_count": len(active_metrics),
        "active_avg_sharpe": active_avg_sharpe,
        "active_median_sharpe": active_median_sharpe,
        "worst_active_mdd": min(drawdowns) if drawdowns else None,
        "labels": {
            "active_avg_sharpe": "Active Avg / Research",
            "active_median_sharpe": "Active Median / Research",
            "worst_active_mdd": "Worst Active / Research",
        },
        "quality_flags": {
            "active_avg_sharpe": "Below 0.80 target" if active_avg_sharpe is not None and active_avg_sharpe < 0.80 else None,
        },
        "basis": (
            "Active strategy research fallback metrics are derived from active ordinary strategy research artifacts; "
            "they are not Combined Portfolio metrics and are not live performance."
        ),
    }


def _cache_ticker_metrics(market_proxy_cache: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    cache = market_proxy_cache or {}
    payload = cache.get("holdings_market_proxy") or cache.get("ticker_market_proxy") or {}
    if isinstance(payload, dict):
        return {str(ticker): deepcopy(value) for ticker, value in payload.items() if isinstance(value, dict)}
    if isinstance(payload, list):
        return {
            str(row["ticker"]): deepcopy(row)
            for row in payload
            if isinstance(row, dict) and row.get("ticker")
        }
    return {}


def _spy_beta_correlation(
    return_rows: list[dict[str, Any]],
    benchmark_returns: dict[str, float],
) -> tuple[float | str, float | str]:
    overlaps = [
        (row["return"], benchmark_returns[row["date"]])
        for row in return_rows
        if row.get("date") in benchmark_returns
    ]
    if len(overlaps) < MARKET_PROXY_MIN_OBSERVATIONS:
        return "Insufficient History", "Insufficient History"
    strategy_returns = [pair[0] for pair in overlaps]
    spy_returns = [pair[1] for pair in overlaps]
    strategy_mean = sum(strategy_returns) / len(strategy_returns)
    spy_mean = sum(spy_returns) / len(spy_returns)
    covariance = sum((s - strategy_mean) * (b - spy_mean) for s, b in overlaps) / (len(overlaps) - 1)
    spy_variance = sum((value - spy_mean) ** 2 for value in spy_returns) / (len(spy_returns) - 1)
    strategy_variance = sum((value - strategy_mean) ** 2 for value in strategy_returns) / (len(strategy_returns) - 1)
    if spy_variance == 0 or strategy_variance == 0:
        return "Not Available", "Not Available"
    beta = covariance / spy_variance
    correlation = covariance / math.sqrt(strategy_variance * spy_variance)
    return beta, correlation


def _research_return_rows(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    series = (strategy.get("research_evidence") or {}).get("research_series") or {}
    dates = series.get("dates") or []
    returns = series.get("return_distribution") or []
    rows = []
    for date, value in zip(dates, returns):
        numeric = _safe_number(value)
        if date and numeric is not None:
            rows.append({"date": str(date), "return": numeric})
    return sorted(rows, key=lambda row: row["date"])


def _research_overlap_count(
    return_rows: list[dict[str, Any]],
    benchmark_returns: dict[str, float],
) -> int:
    return sum(1 for row in return_rows if row.get("date") in benchmark_returns)


def _research_factor_metrics(
    strategy: dict[str, Any],
    benchmark_returns: dict[str, float],
) -> dict[str, Any]:
    evidence = strategy.get("research_evidence") or {}
    metrics = evidence.get("research_metrics") or {}
    return_rows = _research_return_rows(strategy)
    beta, corr = _spy_beta_correlation(return_rows, benchmark_returns)
    vol = _safe_number(metrics.get("annualized_volatility"))
    if vol is None and len(return_rows) >= MARKET_PROXY_MIN_OBSERVATIONS:
        values = [row["return"] for row in return_rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        vol = math.sqrt(variance) * math.sqrt(252)
    has_research = bool(return_rows) or vol is not None
    return {
        "research_beta": beta if has_research else "Insufficient History",
        "research_correlation": corr if has_research else "Insufficient History",
        "research_volatility": vol if vol is not None else "Insufficient History",
        "research_overlap_observations": _research_overlap_count(return_rows, benchmark_returns),
        "research_factor_evidence_class": "Research / Backtest Metric" if has_research else "Insufficient History",
        "research_factor_source": evidence.get("evidence_artifact") or "Not Available",
    }


def _holding_weight(row: dict[str, Any]) -> float | None:
    return _safe_number(
        row.get("current_weight")
        if row.get("current_weight") is not None
        else row.get("target_weight")
    )


def _weighted_holding_metric(
    holdings: list[dict[str, Any]],
    keys: tuple[str, ...],
    ticker_metrics: dict[str, dict[str, Any]] | None = None,
) -> float | str:
    weighted_total = 0.0
    weight_total = 0.0
    metrics = ticker_metrics or {}
    for row in holdings:
        weight = _holding_weight(row)
        if weight is None:
            continue
        ticker_payload = metrics.get(str(row.get("ticker"))) or {}
        value = next(
            (
                _safe_number(source.get(key))
                for source in (row, ticker_payload)
                for key in keys
                if _safe_number(source.get(key)) is not None
            ),
            None,
        )
        if value is None:
            continue
        weighted_total += abs(weight) * value
        weight_total += abs(weight)
    return weighted_total / weight_total if weight_total else "Coverage Missing"


def _weighted_avg_dollar_volume(
    holdings: list[dict[str, Any]],
    ticker_metrics: dict[str, dict[str, Any]] | None = None,
) -> float | str:
    return _weighted_holding_metric(
        holdings,
        ("dollar_volume", "avg_dollar_volume", "average_dollar_volume", "avg_daily_dollar_volume", "avg_dollar_volume_20d", "avg_dollar_volume_30d"),
        ticker_metrics,
    )


def _liquidity_score(weighted_adv: float | str) -> str:
    if not isinstance(weighted_adv, (int, float)):
        return "Not Available"
    if weighted_adv >= 50_000_000:
        return "High"
    if weighted_adv >= 5_000_000:
        return "Medium"
    return "Low"


def _concentration(holdings: list[dict[str, Any]]) -> tuple[float | str, float | str]:
    weights = sorted(
        (abs(weight) for weight in (_holding_weight(row) for row in holdings) if weight is not None),
        reverse=True,
    )
    if not weights:
        return "Not Available", "Not Available"
    return weights[0], sum(weights[:5])


def _sector_top_exposure(
    holdings: list[dict[str, Any]],
    ticker_metrics: dict[str, dict[str, Any]] | None = None,
) -> str:
    sector_weights: dict[str, float] = {}
    metrics = ticker_metrics or {}
    for row in holdings:
        ticker_payload = metrics.get(str(row.get("ticker"))) or {}
        sector = row.get("sector") or row.get("industry") or ticker_payload.get("sector") or ticker_payload.get("industry")
        weight = _holding_weight(row)
        if not sector or weight is None:
            continue
        sector_weights[str(sector)] = sector_weights.get(str(sector), 0.0) + abs(weight)
    if not sector_weights:
        return "Not Available"
    sector, exposure = max(sector_weights.items(), key=lambda item: item[1])
    return f"{sector}: {exposure:.2%}"


def _price_coverage(
    holdings: list[dict[str, Any]],
    strategy: dict[str, Any],
    ticker_metrics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    coverage = strategy.get("price_coverage")
    if isinstance(coverage, dict):
        return deepcopy(coverage)
    if not holdings:
        return {"priced": 0, "total": 0, "status": "Data Pending" if strategy.get("membership_state") == "approved_pending" else "Not Available"}
    priced = sum(
        1
        for row in holdings
        if any(row.get(key) is not None for key in ("latest_price", "simulated_price", "market_price", "close"))
        or any((ticker_metrics or {}).get(str(row.get("ticker")), {}).get(key) is not None for key in ("latest_price", "close"))
    )
    return {
        "priced": priced,
        "total": len(holdings),
        "status": "COMPLETE" if priced == len(holdings) else ("PARTIAL" if priced else "Coverage Missing"),
    }


def _market_proxy_price_rows(fetch_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (
        fetch_result.get("daily_price_history")
        or fetch_result.get("price_history")
        or fetch_result.get("market_proxy_price_history")
        or []
    )
    return [row for row in rows if isinstance(row, dict)]


def _return_series_from_prices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: row.get("date") or row.get("timestamp") or "")
    output = []
    previous_close: float | None = None
    for row in ordered:
        close = _safe_number(row.get("adj_close") if row.get("adj_close") is not None else row.get("close"))
        date = row.get("date") or row.get("timestamp")
        if close is None or not date:
            continue
        if previous_close not in {None, 0}:
            output.append({"date": str(date)[:10], "return": close / previous_close - 1.0})
        previous_close = close
    return output


def _build_market_proxy_cache_from_price_history(
    price_history: list[dict[str, Any]],
    *,
    generated_at: str,
    provider: str,
    requested_tickers: list[str],
    failed_tickers: list[str],
) -> dict[str, Any]:
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in price_history:
        ticker = row.get("ticker") or row.get("symbol")
        if ticker:
            by_ticker.setdefault(str(ticker), []).append(row)
    benchmark_rows = by_ticker.get("SPY", [])
    benchmark_returns = _return_series_from_prices(benchmark_rows)
    holdings_market_proxy = []
    for ticker in sorted(set(requested_tickers) | (set(by_ticker) - {"SPY"})):
        rows = sorted(by_ticker.get(ticker, []), key=lambda row: row.get("date") or row.get("timestamp") or "")
        closes = [
            _safe_number(row.get("adj_close") if row.get("adj_close") is not None else row.get("close"))
            for row in rows
        ]
        closes = [value for value in closes if value is not None]
        latest = closes[-1] if closes else None
        volumes = [_safe_number(row.get("volume")) for row in rows]
        dollar_volumes = [
            close * volume
            for close, volume in zip(closes[-30:], [value for value in volumes if value is not None][-30:])
            if close is not None and volume is not None
        ]
        latest_row = rows[-1] if rows else {}
        momentum_20d = latest / closes[-21] - 1.0 if latest is not None and len(closes) >= 21 and closes[-21] else None
        momentum_63d = latest / closes[-64] - 1.0 if latest is not None and len(closes) >= 64 and closes[-64] else None
        status = "LOADED" if rows else "Coverage Missing"
        holdings_market_proxy.append(
            {
                "ticker": ticker,
                "price_history_coverage": len(rows),
                "latest_price": latest,
                "latest_date": str(latest_row.get("date") or latest_row.get("timestamp") or "")[:10] or None,
                "avg_dollar_volume_20d": (
                    sum(dollar_volumes[-20:]) / len(dollar_volumes[-20:])
                    if len(dollar_volumes) >= 20 else None
                ),
                "avg_dollar_volume_30d": (
                    sum(dollar_volumes[-30:]) / len(dollar_volumes[-30:])
                    if len(dollar_volumes) >= 30 else None
                ),
                "momentum_20d": momentum_20d,
                "momentum_63d": momentum_63d,
                "sector": latest_row.get("sector"),
                "status": status,
                "warning": None if status == "LOADED" else "Ticker history missing from cached delayed yfinance overlay",
            }
        )
    loaded = sum(1 for row in holdings_market_proxy if row["status"] == "LOADED")
    return {
        "metadata": {
            "generated_at": generated_at,
            "provider": provider,
            "delayed_market_data": True,
            "not_live_market_data": True,
            "not_validated_institutional_factor_model": True,
            "requested_ticker_count": len(requested_tickers),
            "loaded_ticker_count": loaded,
            "failed_ticker_count": len(failed_tickers),
            "failed_tickers": sorted(failed_tickers),
        },
        "benchmark": {
            "symbol": "SPY",
            "return_series": benchmark_returns,
            "return_series_dates": [row["date"] for row in benchmark_returns],
            "return_count": len(benchmark_returns),
            "latest_date": benchmark_returns[-1]["date"] if benchmark_returns else None,
            "status": "LOADED" if len(benchmark_returns) >= MARKET_PROXY_MIN_OBSERVATIONS else "Insufficient History",
        },
        "holdings_market_proxy": holdings_market_proxy,
    }


def _market_proxy_cache_from_fetch_result(
    fetch_result: dict[str, Any],
    *,
    generated_at: str,
    requested_tickers: list[str],
) -> dict[str, Any] | None:
    supplied = fetch_result.get("risk_factor_market_proxy_cache")
    if isinstance(supplied, dict):
        return deepcopy(supplied)
    price_history = _market_proxy_price_rows(fetch_result)
    if not price_history:
        return None
    failed = list(fetch_result.get("missing_tickers") or [])
    return _build_market_proxy_cache_from_price_history(
        price_history,
        generated_at=generated_at,
        provider=fetch_result.get("provider") or "yfinance",
        requested_tickers=requested_tickers,
        failed_tickers=failed,
    )


def _risk_factor_market_proxy_table(
    strategies: list[dict[str, Any]],
    canonical: dict[str, Any],
    strategy_daily: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    market_proxy_cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    history_by_id: dict[str, list[dict[str, Any]]] = {}
    holdings_by_id: dict[str, list[dict[str, Any]]] = {}
    cache = _market_proxy_cache(canonical, market_proxy_cache)
    ticker_metrics = _cache_ticker_metrics(cache)
    benchmark_returns = _benchmark_returns_by_date(canonical, cache)
    position_source = canonical.get("position_source") or "committed_shadow_holdings"
    for row in strategy_daily:
        history_by_id.setdefault(row.get("strategy_id"), []).append(row)
    for row in holdings:
        holdings_by_id.setdefault(row.get("strategy_id"), []).append(row)
    rows = []
    for strategy in strategies:
        strategy_id = strategy.get("internal_id")
        if strategy_id in REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS:
            continue
        strategy_history = history_by_id.get(strategy_id, [])
        current_holdings = holdings_by_id.get(strategy_id, [])
        return_rows = _strategy_return_rows(strategy_history)
        pending = strategy.get("membership_state") == "approved_pending"
        combined = strategy_id == "COMBINED_PORTFOLIO"
        spy_beta, spy_correlation = _spy_beta_correlation(return_rows, benchmark_returns)
        research_factors = _research_factor_metrics(strategy, benchmark_returns)
        weighted_adv = _weighted_avg_dollar_volume(current_holdings, ticker_metrics)
        top_holding, top_5 = _concentration(current_holdings)
        price_coverage = _price_coverage(current_holdings, strategy, ticker_metrics)
        warnings = [
            "Not a validated Barra / institutional factor model",
            "Not live brokerage",
            "Not live real-time market data",
        ]
        if pending:
            proxy_status = "Pending / Pre-operational"
            data_status = "Data Pending"
            warnings.append("Operational rows pending admission")
        elif combined:
            proxy_status = "Constituent-Derived Pending" if len(return_rows) < MARKET_PROXY_MIN_OBSERVATIONS else "Market Data Proxy"
            data_status = "Derived from ordinary strategy operational ledgers"
        elif len(return_rows) < MARKET_PROXY_MIN_OBSERVATIONS:
            proxy_status = "Insufficient History"
            data_status = "Operational returns loaded; insufficient market proxy history"
        else:
            proxy_status = "Market Data Proxy"
            data_status = "Operational returns loaded"
        if not benchmark_returns:
            warnings.append("SPY benchmark return history not loaded in operational artifacts")
        if price_coverage["total"] and price_coverage["priced"] < price_coverage["total"]:
            warnings.append("Delayed yfinance price coverage incomplete")
        elif not price_coverage["total"] and not pending and not combined:
            warnings.append("Holdings coverage missing")
        if pending:
            null_or_pending: float | str | None = "Not Applicable"
            current_drawdown: float | str | None = "Not Applicable"
        else:
            null_or_pending = None
            current_drawdown = (
                strategy.get("current_drawdown")
                if strategy.get("current_drawdown") is not None
                else (strategy_history[-1].get("current_drawdown") if strategy_history else "Not Available")
            )
        rows.append(
            {
                "strategy_id": strategy_id,
                "display_id": strategy.get("display_id"),
                "display_name": strategy.get("display_name") or strategy.get("name") or "N/A",
                "sleeve_type": _sleeve_type(strategy),
                "primary_status": _primary_status(strategy),
                "current_weight": None if pending else strategy.get("current_weight"),
                "capital": None if pending else strategy.get("ending_nav"),
                "position_source": position_source,
                "history_observation_count": len(return_rows),
                "holdings_count": len(current_holdings),
                "price_coverage": price_coverage,
                "spy_beta": null_or_pending or spy_beta,
                "spy_correlation": null_or_pending or spy_correlation,
                "realized_vol_20d": null_or_pending or _annualized_realized_vol(return_rows, 20),
                "realized_vol_60d": null_or_pending or _annualized_realized_vol(return_rows, 60),
                "research_beta": null_or_pending or research_factors["research_beta"],
                "research_correlation": null_or_pending or research_factors["research_correlation"],
                "research_volatility": null_or_pending or research_factors["research_volatility"],
                "research_overlap_observations": 0 if pending else research_factors["research_overlap_observations"],
                "research_factor_evidence_class": "Not Applicable" if pending else research_factors["research_factor_evidence_class"],
                "research_factor_source": "Not Applicable" if pending else research_factors["research_factor_source"],
                "current_drawdown": current_drawdown,
                "momentum_20d": null_or_pending or _weighted_holding_metric(current_holdings, ("momentum_20d", "return_20d", "price_return_20d"), ticker_metrics),
                "momentum_63d": null_or_pending or _weighted_holding_metric(current_holdings, ("momentum_63d", "return_63d", "price_return_63d"), ticker_metrics),
                "liquidity_score": null_or_pending or _liquidity_score(weighted_adv),
                "weighted_avg_dollar_volume": null_or_pending or weighted_adv,
                "top_holding_concentration": null_or_pending or top_holding,
                "top_5_concentration": null_or_pending or top_5,
                "sector_top_exposure": null_or_pending or _sector_top_exposure(current_holdings, ticker_metrics),
                "data_status": data_status,
                "proxy_status": proxy_status,
                "warnings": warnings,
                "evidence_source": MARKET_PROXY_DISCLOSURE,
            }
        )
    return rows


def _risk_factor_big_table(strategies: list[dict[str, Any]], canonical: dict[str, Any]) -> list[dict[str, Any]]:
    """Build strategy/sleeve risk-factor rows from loaded snapshot records only."""
    status = canonical.get("operational_status") or {}
    position_source = canonical.get("position_source") or "committed_shadow_holdings"
    position_disclosure = canonical.get(
        "position_source_disclosure",
        "Committed shadow holdings; no live brokerage positions or fills represented.",
    )
    rows = []
    for strategy in strategies:
        factor_summary = strategy.get("factor_exposure") or strategy.get("factor_metadata") or {}
        pending = strategy.get("membership_state") == "approved_pending"
        combined = strategy.get("internal_id") == "COMBINED_PORTFOLIO"
        source_note = "ordinary strategy operational daily ledgers" if combined else _evidence_source(strategy)
        rows.append(
            {
                "strategy_id": strategy.get("internal_id"),
                "display_id": strategy.get("display_id"),
                "display_name": strategy.get("display_name") or strategy.get("name") or "N/A",
                "sleeve_type": _sleeve_type(strategy),
                "primary_status": _primary_status(strategy),
                "capital_weight": strategy.get("sleeve_weight") if not pending else None,
                "nav": None if pending else strategy.get("ending_nav"),
                "daily_pnl": None if pending else strategy.get("daily_pnl"),
                "daily_return": None if pending else strategy.get("daily_return"),
                "economic_logic": strategy.get("hypothesis_summary") or "Missing Metadata",
                "primary_risk_driver": strategy.get("primary_risk_driver") or (
                    f"Strategy family: {strategy.get('family')}" if strategy.get("family") else "Missing Metadata"
                ),
                "factor_exposure_summary": factor_summary.get("summary") or "Missing Metadata",
                "market_exposure": _missing_factor_value(factor_summary.get("market")),
                "size_exposure": _missing_factor_value(factor_summary.get("size")),
                "value_exposure": _missing_factor_value(factor_summary.get("value")),
                "momentum_exposure": _missing_factor_value(factor_summary.get("momentum")),
                "quality_exposure": _missing_factor_value(factor_summary.get("quality")),
                "volatility_exposure": _missing_factor_value(factor_summary.get("volatility")),
                "liquidity_exposure": _missing_factor_value(factor_summary.get("liquidity")),
                "correlation_diversification_note": (
                    "Derived composite of ordinary active strategies; pairwise operational correlation remains gated."
                    if combined else status.get("correlation", {}).get("status") or "Not Available"
                ),
                "drawdown_risk_note": (
                    "Data Pending" if pending
                    else "N/A" if strategy.get("current_drawdown") is None
                    else f"Current drawdown loaded from operational ledger: {strategy.get('current_drawdown')}"
                ),
                "position_source": position_source,
                "position_source_disclosure": position_disclosure,
                "legacy_artifact_position_estimate_authoritative": False,
                "latest_signal_date": strategy.get("last_signal") or strategy.get("latest_signal_date"),
                "latest_execution_date": None if pending else strategy.get("last_execution"),
                "evidence_artifact_source": source_note,
                "missing_data_warning": _missing_warning(strategy, factor_summary),
            }
        )
    return rows


def build_operational_snapshot(
    canonical: dict[str, Any],
    *,
    intraday: dict[str, Any] | None = None,
    market_proxy_cache: dict[str, Any] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    operational_pricing_universe_size: int | None = None,
    strategy_research_details: dict[str, Any] | None = None,
    sp500_reference_universe: dict[str, Any] | None = None,
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
            trade["status"] = PROVENANCE_LABELS[trade["execution_provenance"]]
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
                "current_weight": None if source.get("membership_state") == "approved_pending" else source.get("current_weight"),
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
            strategy_record["current_operational_label"] = "APPROVED_PENDING / PRE_OPERATIONAL"
            strategy_record["paper_fill_status"] = "No Paper Fill"
            strategy_record["live_brokerage_fill"] = "Disabled / No Live Brokerage Fill"
            strategy_record["action"] = "PENDING ADMISSION"
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
    trading_session_lifecycle = _trading_session_lifecycle(
        portfolio_daily=portfolio_daily,
        strategy_daily=strategy_daily,
        trades=trades,
        holdings=holdings,
        official=official,
        intraday_estimate=intraday_estimate,
        refresh_meta=refresh_meta,
    )
    official_readiness = official_promotion_readiness({"trading_session_lifecycle": trading_session_lifecycle})
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
    risk_factor_big_table = _risk_factor_big_table(strategies, canonical)
    risk_factor_market_proxy_table = _risk_factor_market_proxy_table(
        strategies,
        canonical,
        strategy_daily,
        published_holdings,
        market_proxy_cache,
    )
    sp500_reference_payload = _sp500_reference_universe_payload(sp500_reference_universe)
    benchmark_reference_payload = _benchmark_reference_payload(canonical, market_proxy_cache)
    risk_factor_contract_summary = _risk_factor_contract_summary(risk_factor_market_proxy_table)
    research_summary = _research_summary_payload(strategies)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id or f"ops-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
        "generated_at": generated,
        "refresh_status": refresh_status,
        "data_freshness": refresh_meta.get("data_freshness") or ("DELAYED" if intraday else "OFFICIAL_CLOSE"),
        "market_session_status": trading_session_lifecycle["market_session_status"],
        "market_data_as_of": intraday_estimate["market_data_as_of"],
        "latest_official_ledger_date": trading_session_lifecycle["latest_official_ledger_date"],
        "official_close_as_of": trading_session_lifecycle["official_close_as_of"],
        "delayed_estimate_as_of": trading_session_lifecycle["delayed_estimate_as_of"],
        "current_trading_session_date": trading_session_lifecycle["current_trading_session_date"],
        "official_promotion_blockers": trading_session_lifecycle["official_promotion_blockers"],
        "trading_session_lifecycle": trading_session_lifecycle,
        "official_promotion_readiness": official_readiness,
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
        "risk_factor_big_table": risk_factor_big_table,
        "risk_factor_market_proxy_table": risk_factor_market_proxy_table,
        "risk_factors": risk_factor_contract_summary,
        "research_summary": research_summary,
        "benchmark_reference": benchmark_reference_payload,
        "sp500_reference_universe": sp500_reference_payload,
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
            "basis": "Top-level strategy analytics use the 17 current active sleeves: 16 ordinary active strategies plus the active Combined strategy. Removed non-operating research candidates are not part of the current workstation operating set.",
        },
        "strategy_entity_inventory": entity_inventory,
        "strategy_cost_reconciliation": strategy_cost_reconciliation,
        "operational_status": deepcopy(canonical["operational_status"]),
        "pending_membership": None,
        "removed_from_current_workstation_strategy_ids": sorted(REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS),
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
            and existing.get("official_promotion_readiness")
            and existing.get("risk_factor_big_table")
            and existing.get("risk_factor_market_proxy_table")
            and existing.get("benchmark_reference")
            and existing.get("sp500_reference_universe")
            and isinstance(existing.get("risk_factors"), dict)
            and isinstance(existing.get("research_summary"), dict)
            and isinstance(existing.get("removed_from_current_workstation_strategy_ids"), list)
            and (
                not paths["sp500_reference_universe"].exists()
                or existing.get("sp500_reference_universe", {}).get("status") == "LOADED"
            )
            and not existing.get("intraday_estimate", {}).get("provider")
            and (not _research_mapping_available(root) or _snapshot_research_evidence(existing))
        ):
            return _attach_paper_portfolio_daily_fields(root, existing)
    canonical = _read_json(paths["canonical"], {})
    market_proxy_cache = _read_json(paths["market_proxy_cache"], {})
    sp500_reference_universe = _read_json(paths["sp500_reference_universe"], None)
    source = _read_json(paths["source_bundle"], {}).get("shadow_live", {})
    research = load_strategy_research_artifacts(root, canonical["strategies"])
    snapshot = build_operational_snapshot(
        canonical,
        intraday=None,
        market_proxy_cache=market_proxy_cache,
        sp500_reference_universe=sp500_reference_universe,
        decisions=read_decisions(root),
        operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
        strategy_research_details=research,
    )
    snapshot = _attach_paper_portfolio_daily_fields(root, snapshot)
    _atomic_write_json(paths["snapshot"], snapshot)
    return snapshot


def _attach_paper_portfolio_daily_fields(root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(snapshot)
    payload = paper_portfolio_snapshot_payload(root)
    enriched["official_ledger_daily"] = deepcopy(enriched.get("portfolio_daily") or [])
    enriched["paper_performance_daily"] = payload["rows"]
    enriched["paper_performance_daily_metadata"] = payload["metadata"]
    return enriched


def _research_mapping_available(root: Path) -> bool:
    return (root / "data/config/strategy_research_mapping.json").exists()


def _snapshot_research_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        row["internal_id"]: row["research_evidence"]
        for row in snapshot.get("strategies", [])
        if row.get("internal_id") and row.get("research_evidence")
    }


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_overlay_stale(overlay: dict[str, Any], *, now: datetime | None = None) -> bool:
    generated = _parse_iso_timestamp(overlay.get("generated_at"))
    if generated is None:
        return True
    stale_after = int(overlay.get("stale_after_seconds") or INTRADAY_OVERLAY_STALE_AFTER_SECONDS)
    current = now or datetime.now(timezone.utc)
    return (current - generated).total_seconds() > stale_after


def _read_intraday_overlay(root: Path) -> dict[str, Any] | None:
    overlay = _read_json(_paths(root)["intraday_overlay"], {})
    return overlay or None


def _read_latest_refresh_snapshot(root: Path) -> dict[str, Any] | None:
    pointer = _read_json(root / "output/intraday_latest.json", {})
    raw_path = pointer.get("path")
    if not raw_path:
        return None
    snapshot_path = Path(str(raw_path))
    if not snapshot_path.is_absolute():
        snapshot_path = root / snapshot_path
    snapshot = _read_json(snapshot_path, {})
    return snapshot or None


def _intraday_from_overlay(overlay: dict[str, Any]) -> dict[str, Any] | None:
    if overlay.get("schema_version") != INTRADAY_OVERLAY_SCHEMA_VERSION:
        return None
    if overlay.get("status") != "LOADED":
        return None
    coverage = overlay.get("price_coverage") or {}
    return {
        "provider": overlay.get("provider"),
        "estimated_nav": overlay.get("estimated_nav"),
        "estimated_pnl": overlay.get("estimated_pnl"),
        "market_data_as_of": overlay.get("delayed_estimate_as_of"),
        "covered_tickers": coverage.get("covered"),
        "total_tickers": coverage.get("total"),
        "missing_tickers": overlay.get("missing_tickers") or [],
        "stale_tickers": overlay.get("stale_tickers") or [],
        "residual_pnl": overlay.get("residual_pnl"),
        "holdings": overlay.get("holdings") or [],
        "strategy_contribution": {
            row["internal_id"]: row.get("estimated_pnl")
            for row in overlay.get("strategy_estimates") or []
            if row.get("internal_id")
        },
        "ticker_security_contribution": overlay.get("ticker_security_contribution") or [],
        "refresh_meta": {
            "data_freshness": "DELAYED",
            "market_session_status": overlay.get("market_session_status"),
            "session_date": overlay.get("current_trading_session_date"),
            "last_successful_refresh": overlay.get("generated_at"),
            "next_refresh": overlay.get("next_refresh"),
        },
        "risk_factor_market_proxy_cache": overlay.get("risk_factor_market_proxy_cache"),
    }


def _latest_paper_row_for_session(root: Path, session_date: str | None) -> dict[str, Any] | None:
    if not session_date:
        return None
    rows = paper_portfolio_snapshot_payload(root, limit=10_000).get("rows") or []
    matches = [row for row in rows if (row.get("trading_date") or row.get("date")) == session_date]
    return matches[-1] if matches else None


def _intraday_from_latest_prices(
    canonical: dict[str, Any],
    latest_prices: dict[str, Any],
    *,
    latest_as_of: str | None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    if not latest_prices:
        return [], {}
    current_holdings = _current_holdings(canonical.get("holdings") or [])
    enriched_holdings: list[dict[str, Any]] = []
    strategy_contribution: dict[str, float] = {}
    for row in current_holdings:
        ticker = row.get("ticker")
        price_payload = latest_prices.get(str(ticker)) if ticker is not None else None
        latest_price = None
        latest_timestamp = latest_as_of
        if isinstance(price_payload, dict):
            latest_price = price_payload.get("price") or price_payload.get("close") or price_payload.get("latest_price")
            latest_timestamp = price_payload.get("timestamp") or price_payload.get("observation_ts_et") or latest_as_of
        elif price_payload is not None:
            latest_price = price_payload
        estimated_pnl = None
        if latest_price is not None and row.get("simulated_quantity") is not None and row.get("simulated_execution_price") is not None:
            estimated_pnl = float(row["simulated_quantity"]) * (
                float(latest_price) - float(row["simulated_execution_price"])
            )
            strategy_id = row.get("strategy_id")
            if strategy_id:
                strategy_contribution[strategy_id] = strategy_contribution.get(strategy_id, 0.0) + estimated_pnl
        enriched_holdings.append(
            {
                **row,
                "latest_price": latest_price,
                "latest_price_source": "Delayed Market Price" if latest_price is not None else None,
                "latest_delayed_price_as_of": latest_timestamp if latest_price is not None else None,
                "data_as_of": latest_timestamp if latest_price is not None else None,
                "daily_estimated_pnl": estimated_pnl,
                "estimated_contribution": estimated_pnl,
                "intraday_estimate_method": "delayed mark against current paper holding execution price",
            }
        )
    return enriched_holdings, strategy_contribution


def _intraday_from_refresh_snapshot(root: Path, snapshot: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    session_date = snapshot.get("market_session_date") or (snapshot.get("shadow_intraday") or {}).get("session_date")
    paper_row = _latest_paper_row_for_session(root, session_date)
    marks = snapshot.get("marks") or {}
    data_quality = marks.get("data_quality") or {}
    shadow = snapshot.get("shadow_intraday") or {}
    latest_prices = snapshot.get("latest_usable_prices") or shadow.get("latest_usable_prices") or {}
    estimated_pnl = shadow.get("estimated_pnl")
    if estimated_pnl is None:
        estimated_pnl = marks.get("estimated_intraday_pnl")
    if estimated_pnl is None and paper_row:
        estimated_pnl = paper_row.get("daily_pnl") or paper_row.get("net_pnl")
    estimated_nav = marks.get("estimated_intraday_nav")
    if estimated_nav is None and shadow.get("estimated_return") is not None and marks.get("baseline_model_nav") is not None:
        estimated_nav = float(marks["baseline_model_nav"]) * (1.0 + float(shadow["estimated_return"]))
    if estimated_nav is None and paper_row:
        estimated_nav = paper_row.get("ending_nav") or paper_row.get("nav")
    latest_as_of = (
        data_quality.get("latest_completed_bar_ts_et")
        or snapshot.get("latest_completed_bar_ts_et")
        or snapshot.get("latest_observation_ts_et")
        or (paper_row or {}).get("as_of_time")
    )
    covered = snapshot.get("ticker_count_successful")
    total = snapshot.get("ticker_count_requested")
    if estimated_nav is None and estimated_pnl is None and latest_as_of is None:
        return None
    canonical = _read_json(_paths(root)["canonical"], {})
    enriched_holdings, price_strategy_contribution = _intraday_from_latest_prices(
        canonical,
        latest_prices,
        latest_as_of=latest_as_of,
    )
    snapshot_strategy_contribution = {
        row["strategy_id"]: row.get("estimated_pnl")
        for row in shadow.get("strategies") or []
        if row.get("strategy_id") and row.get("estimated_pnl") is not None
    }
    strategy_contribution = snapshot_strategy_contribution or price_strategy_contribution
    freshness = str(data_quality.get("freshness") or "").upper()
    status = "STALE" if freshness == "STALE" else "LOADED"
    return (
        {
            "provider": snapshot.get("provider") or "yfinance",
            "estimated_nav": estimated_nav,
            "estimated_pnl": estimated_pnl,
            "market_data_as_of": latest_as_of,
            "covered_tickers": covered,
            "total_tickers": total,
            "missing_tickers": snapshot.get("missing_tickers") or [],
            "stale_tickers": snapshot.get("stale_tickers") or [],
            "residual_pnl": None,
            "holdings": enriched_holdings,
            "strategy_contribution": strategy_contribution,
            "ticker_security_contribution": [],
            "refresh_meta": {
                "data_freshness": freshness or "DELAYED",
                "market_session_status": snapshot.get("market_session_status"),
                "session_date": session_date,
                "last_successful_refresh": snapshot.get("refresh_completed_at"),
                "next_refresh": None,
            },
            "risk_factor_market_proxy_cache": marks.get("risk_factor_market_proxy_cache"),
        },
        status,
    )


def _refresh_snapshot_overlay_metadata(snapshot: dict[str, Any], intraday: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "schema_version": "intraday_snapshot_store_v1",
        "generated_at": snapshot.get("refresh_completed_at"),
        "status": status,
        "provider": intraday.get("provider"),
        "delayed_estimate_as_of": intraday.get("market_data_as_of"),
        "current_trading_session_date": intraday.get("refresh_meta", {}).get("session_date"),
        "missing_tickers": intraday.get("missing_tickers") or [],
        "stale_tickers": intraday.get("stale_tickers") or [],
        "price_coverage": {
            "covered": intraday.get("covered_tickers"),
            "total": intraday.get("total_tickers"),
        },
        "refresh_cadence_minutes": max(int(snapshot.get("refresh_interval_minutes") or 30), 30),
        "errors": [],
    }


def _runtime_message(status: str, overlay: dict[str, Any] | None) -> str:
    if status == "LOADED":
        as_of = (overlay or {}).get("delayed_estimate_as_of") or "N/A"
        return f"Delayed estimate loaded as-of {as_of}; not official ledger."
    if status == "STALE":
        as_of = (overlay or {}).get("delayed_estimate_as_of") or "N/A"
        return f"Last delayed estimate as-of {as_of} is stale; official ledger unchanged."
    if status == "ERROR":
        errors = (overlay or {}).get("errors") or ["Delayed estimate refresh failed."]
        return f"{errors[0]} Official ledger unchanged."
    return "Delayed estimate not loaded; official ledger remains separate."


def _attach_intraday_runtime_fields(
    snapshot: dict[str, Any],
    *,
    status: str,
    overlay: dict[str, Any] | None,
    scheduler_enabled: bool,
    available: bool,
) -> dict[str, Any]:
    enriched = deepcopy(snapshot)
    enriched["intraday_runtime_status"] = status
    enriched["intraday_overlay_available"] = available
    enriched["intraday_scheduler_enabled"] = bool(scheduler_enabled)
    enriched["intraday_refresh_message"] = _runtime_message(status, overlay)
    enriched["intraday_refresh_cadence_minutes"] = (overlay or {}).get("refresh_cadence_minutes") or 30
    enriched["intraday_overlay_metadata"] = {
        "schema_version": (overlay or {}).get("schema_version"),
        "generated_at": (overlay or {}).get("generated_at"),
        "status": status,
        "stale_after_seconds": (overlay or {}).get("stale_after_seconds"),
        "refresh_cadence_minutes": (overlay or {}).get("refresh_cadence_minutes") or 30,
        "delayed_estimate_as_of": (overlay or {}).get("delayed_estimate_as_of"),
        "current_trading_session_date": (overlay or {}).get("current_trading_session_date"),
        "errors": (overlay or {}).get("errors") or [],
    }
    return enriched


def _snapshot_from_latest_refresh(
    root: Path,
    base: dict[str, Any],
    *,
    scheduler_enabled: bool,
) -> dict[str, Any] | None:
    latest_snapshot = _read_latest_refresh_snapshot(root)
    latest_intraday = _intraday_from_refresh_snapshot(root, latest_snapshot) if latest_snapshot else None
    if not latest_intraday:
        return None
    intraday, status = latest_intraday
    canonical = _read_json(_paths(root)["canonical"], {})
    market_proxy_cache = _read_json(_paths(root)["market_proxy_cache"], {})
    sp500_reference_universe = _read_json(_paths(root)["sp500_reference_universe"], None)
    source = _read_json(_paths(root)["source_bundle"], {}).get("shadow_live", {})
    merged = build_operational_snapshot(
        canonical,
        intraday=intraday,
        market_proxy_cache=market_proxy_cache or intraday.get("risk_factor_market_proxy_cache"),
        sp500_reference_universe=sp500_reference_universe,
        decisions=read_decisions(root),
        operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
        strategy_research_details=_snapshot_research_evidence(base),
        refresh_status=status,
    )
    merged = _attach_paper_portfolio_daily_fields(root, merged)
    return _attach_intraday_runtime_fields(
        merged,
        status=status,
        overlay=_refresh_snapshot_overlay_metadata(latest_snapshot, intraday, status),
        scheduler_enabled=scheduler_enabled,
        available=True,
    )


def load_operational_snapshot_for_response(
    root: Path,
    *,
    scheduler_enabled: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return official base snapshot merged with a fresh delayed overlay when available."""
    base = load_or_build_operational_snapshot(root)
    overlay = _read_intraday_overlay(root)
    if not overlay:
        latest = _snapshot_from_latest_refresh(root, base, scheduler_enabled=scheduler_enabled)
        if latest:
            return latest
        return _attach_intraday_runtime_fields(
            base,
            status="NOT_LOADED",
            overlay=None,
            scheduler_enabled=scheduler_enabled,
            available=False,
        )
    if overlay.get("status") == "ERROR":
        return _attach_intraday_runtime_fields(
            base,
            status="ERROR",
            overlay=overlay,
            scheduler_enabled=scheduler_enabled,
            available=False,
        )
    if overlay.get("status") != "LOADED" or _is_overlay_stale(overlay, now=now):
        latest = _snapshot_from_latest_refresh(root, base, scheduler_enabled=scheduler_enabled)
        if latest:
            return latest
        return _attach_intraday_runtime_fields(
            base,
            status="STALE" if overlay.get("status") == "LOADED" else str(overlay.get("status") or "NOT_LOADED"),
            overlay=overlay,
            scheduler_enabled=scheduler_enabled,
            available=False,
        )
    intraday = _intraday_from_overlay(overlay)
    if intraday is None:
        return _attach_intraday_runtime_fields(
            base,
            status="ERROR",
            overlay={
                **overlay,
                "errors": ["Intraday overlay schema is invalid for dashboard merge."],
            },
            scheduler_enabled=scheduler_enabled,
            available=False,
        )
    canonical = _read_json(_paths(root)["canonical"], {})
    market_proxy_cache = _read_json(_paths(root)["market_proxy_cache"], {})
    sp500_reference_universe = _read_json(_paths(root)["sp500_reference_universe"], None)
    source = _read_json(_paths(root)["source_bundle"], {}).get("shadow_live", {})
    merged = build_operational_snapshot(
        canonical,
        intraday=intraday,
        market_proxy_cache=market_proxy_cache or overlay.get("risk_factor_market_proxy_cache"),
        sp500_reference_universe=sp500_reference_universe,
        decisions=read_decisions(root),
        operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
        strategy_research_details=_snapshot_research_evidence(base),
        refresh_status="SUCCESS",
    )
    merged = _attach_paper_portfolio_daily_fields(root, merged)
    return _attach_intraday_runtime_fields(
        merged,
        status="LOADED",
        overlay=overlay,
        scheduler_enabled=scheduler_enabled,
        available=True,
    )


def read_operational_intraday_overlay(root: Path) -> dict[str, Any] | None:
    """Public test/audit helper for the runtime delayed estimate overlay."""
    return _read_intraday_overlay(root)


def refresh_operational_snapshot(
    root: Path,
    *,
    fetch_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh delayed intraday estimates into a runtime overlay without mutating official ledger rows."""
    paths = _paths(root)
    with snapshot_refresh_lock(paths["lock"]) as acquired:
        if not acquired:
            return {"ok": False, "refresh_status": "REFRESHING", "error": "refresh_already_in_progress"}
        base = load_or_build_operational_snapshot(root)
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
            market_proxy_cache = _market_proxy_cache_from_fetch_result(
                fetched,
                generated_at=now.isoformat(),
                requested_tickers=tickers,
            )
            session = market_session_status(interval_minutes=5)
            priced_tickers = len(bars)
            freshness = "STALE" if missing or stale or priced_tickers < len(tickers) else "DELAYED"
            paper_refresh_status = "partial" if missing or stale or priced_tickers < len(tickers) else "fresh"
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
                    "session_date": session.session_date,
                    "last_successful_refresh": now.isoformat(),
                    "next_refresh": (now + timedelta(seconds=REFRESH_INTERVAL_SECONDS)).isoformat(),
                },
            }
            paper_update = {
                "portfolio_row_updated": False,
                "strategy_rows_updated": 0,
                "reason": "no_usable_delayed_estimate",
            }
            if estimated_pnl is not None and official_nav not in {None, 0} and priced_tickers > 0:
                paper_payload = upsert_paper_portfolio_daily(
                    root,
                    {
                        "date": session.session_date,
                        "trading_date": session.session_date,
                        "as_of_time": latest_price_as_of,
                        "source": "Paper Portfolio Daily Ledger",
                        "source_artifact": "dashboard/data/performance/paper_portfolio_daily.json",
                        "position_source": "committed_shadow_holdings",
                        "paper_only": True,
                        "delayed_market_data": True,
                        "not_live_market_data": True,
                        "live_brokerage_execution": False,
                        "is_official_ledger": False,
                        "provider": intraday["provider"],
                        "prior_nav": official_nav,
                        "beginning_nav": official_nav,
                        "nav": intraday["estimated_nav"],
                        "ending_nav": intraday["estimated_nav"],
                        "daily_pnl": estimated_pnl,
                        "net_pnl": estimated_pnl,
                        "daily_return": estimated_pnl / official_nav,
                        "refresh_status": paper_refresh_status,
                        "ticker_count_requested": len(tickers),
                        "ticker_count_successful": priced_tickers,
                        "covered_weight": None,
                        "priced_tickers": sorted(bars),
                        "missing_tickers": sorted(missing),
                        "stale_tickers": sorted(stale),
                        "warnings": (
                            [f"partial delayed market coverage ({priced_tickers}/{len(tickers)})"]
                            if paper_refresh_status == "partial" else []
                        ),
                    },
                )
                paper_update = {
                    "portfolio_row_updated": True,
                    "strategy_rows_updated": 0,
                    "trading_date": session.session_date,
                    "nav": intraday["estimated_nav"],
                    "daily_pnl": estimated_pnl,
                    "daily_return": estimated_pnl / official_nav,
                    "refresh_status": paper_refresh_status,
                    "row_count": len(paper_payload.get("rows") or []),
                    "paper_only": True,
                    "delayed_market_data": True,
                    "not_live_market_data": True,
                    "is_official_ledger": False,
                }
            merged = build_operational_snapshot(
                canonical,
                intraday=intraday,
                market_proxy_cache=market_proxy_cache,
                sp500_reference_universe=_read_json(paths["sp500_reference_universe"], None),
                decisions=read_decisions(root),
                operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
                strategy_research_details=_snapshot_research_evidence(base),
                refresh_status="SUCCESS" if freshness == "DELAYED" else "STALE",
            )
            overlay = {
                "schema_version": INTRADAY_OVERLAY_SCHEMA_VERSION,
                "generated_at": now.isoformat(),
                "status": "LOADED",
                "provider": intraday["provider"],
                "current_trading_session_date": session.session_date,
                "market_session_status": session.status,
                "delayed_estimate_as_of": latest_price_as_of,
                "estimated_nav": intraday["estimated_nav"],
                "estimated_pnl": intraday["estimated_pnl"],
                "estimated_return": (
                    intraday["estimated_pnl"] / official_nav
                    if official_nav not in {None, 0} and intraday["estimated_pnl"] is not None
                    else None
                ),
                "price_coverage": {
                    "covered": priced_tickers,
                    "total": len(tickers),
                },
                "strategy_estimates": [
                    {
                        "internal_id": row["internal_id"],
                        "display_id": row.get("display_id"),
                        "display_name": row.get("display_name"),
                        "estimated_pnl": row.get("intraday_estimated_pnl"),
                        "estimated_nav": row.get("intraday_estimated_nav"),
                        "unavailable_reason": row.get("intraday_estimate_unavailable_reason"),
                    }
                    for row in merged.get("strategies", [])
                ],
                "top_contributors": merged.get("top_contributors") or [],
                "top_detractors": merged.get("top_detractors") or [],
                "ticker_security_contribution": intraday["ticker_security_contribution"],
                "holdings": enriched_holdings,
                "missing_tickers": sorted(missing),
                "stale_tickers": sorted(stale),
                "residual_pnl": intraday["residual_pnl"],
                "risk_factor_market_proxy_cache": market_proxy_cache,
                "errors": [],
                "stale_after_seconds": INTRADAY_OVERLAY_STALE_AFTER_SECONDS,
                "next_refresh": intraday["refresh_meta"]["next_refresh"],
                "official_ledger_unchanged": True,
                "paper_performance_update": paper_update,
            }
            _atomic_write_json(paths["intraday_overlay"], overlay)
            if market_proxy_cache:
                _atomic_write_json(paths["market_proxy_cache"], market_proxy_cache)
            _atomic_write_json(
                paths["status"],
                {
                    "state": "SUCCESS" if freshness == "DELAYED" else "STALE",
                    "overlay_status": "LOADED",
                    "snapshot_id": base.get("snapshot_id"),
                    "overlay_generated_at": now.isoformat(),
                    "at": now.isoformat(),
                },
            )
            response = load_operational_snapshot_for_response(root, scheduler_enabled=False, now=now)
            return {"ok": True, "paper_performance_update": paper_update, **response}
        except Exception as exc:
            failed_at = datetime.now(timezone.utc).isoformat()
            error_overlay = {
                "schema_version": INTRADAY_OVERLAY_SCHEMA_VERSION,
                "generated_at": failed_at,
                "status": "ERROR",
                "provider": None,
                "current_trading_session_date": None,
                "market_session_status": None,
                "delayed_estimate_as_of": None,
                "estimated_nav": None,
                "estimated_pnl": None,
                "estimated_return": None,
                "price_coverage": {"covered": None, "total": None},
                "strategy_estimates": [],
                "top_contributors": [],
                "top_detractors": [],
                "errors": [str(exc)],
                "stale_after_seconds": INTRADAY_OVERLAY_STALE_AFTER_SECONDS,
                "official_ledger_unchanged": True,
            }
            _atomic_write_json(paths["intraday_overlay"], error_overlay)
            _atomic_write_json(
                paths["status"],
                {"state": "FAILED", "overlay_status": "ERROR", "snapshot_id": base.get("snapshot_id"), "failed_at": failed_at, "error": str(exc)},
            )
            return {
                "ok": False,
                "refresh_status": "ERROR",
                "intraday_runtime_status": "ERROR",
                "intraday_overlay_available": False,
                "snapshot_id": base.get("snapshot_id"),
                "generated_at": base.get("generated_at"),
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
        intraday=None,
        sp500_reference_universe=_read_json(_paths(root)["sp500_reference_universe"], None),
        decisions=decisions,
        operational_pricing_universe_size=source.get("operational_pricing_universe_size"),
        strategy_research_details=_snapshot_research_evidence(prior),
        refresh_status="DECISION_RECORDED",
    )
    _atomic_write_json(_paths(root)["snapshot"], snapshot)
    return decision
