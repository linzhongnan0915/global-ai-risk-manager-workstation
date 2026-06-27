from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PAPER_PORTFOLIO_DAILY_RELATIVE_PATH = Path("dashboard/data/performance/paper_portfolio_daily.json")
PAPER_STRATEGY_DAILY_RELATIVE_PATH = Path("dashboard/data/performance/paper_strategy_daily.json")
PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION = "paper_portfolio_daily_v1"
PAPER_STRATEGY_DAILY_SCHEMA_VERSION = "paper_strategy_daily_v1"
PAPER_REBALANCE_DIR = Path("data/paper_rebalance")


def paper_portfolio_daily_path(root: Path) -> Path:
    return root / PAPER_PORTFOLIO_DAILY_RELATIVE_PATH


def paper_strategy_daily_path(root: Path) -> Path:
    return root / PAPER_STRATEGY_DAILY_RELATIVE_PATH


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _latest_date(rows: list[dict[str, Any]]) -> str:
    return max((str(row.get("date") or "") for row in rows), default="")


def _strategy_id(row: dict[str, Any]) -> str | None:
    value = row.get("strategy_id") or row.get("internal_id") or row.get("id")
    return str(value) if value else None


def applied_paper_rebalance_for_date(root: Path, trading_date: str | None) -> dict[str, Any]:
    """Return applied paper target weights and effective-date costs without touching official ledgers."""
    target = _read_json(root / PAPER_REBALANCE_DIR / "current_paper_target_weights.json", None)
    plans = _read_json(root / PAPER_REBALANCE_DIR / "paper_rebalance_plans.json", {"plans": []})
    if not isinstance(target, dict):
        return {
            "applied": False,
            "weights": {},
            "transaction_cost_total": 0.0,
            "cost_by_strategy": {},
            "applied_plan_id": None,
            "intended_effective_date": None,
        }
    plan_id = target.get("applied_plan_id")
    matched_plan = next(
        (plan for plan in plans.get("plans") or [] if plan.get("plan_id") == plan_id),
        None,
    )
    intended_effective_date = target.get("intended_effective_date") or (matched_plan or {}).get("intended_effective_date")
    cost_applies = bool(trading_date and intended_effective_date == trading_date)
    cost_by_strategy: dict[str, float] = {}
    if cost_applies and isinstance(target.get("cost_by_strategy"), dict):
        cost_by_strategy = {
            str(strategy_id): float(cost)
            for strategy_id, cost in target.get("cost_by_strategy", {}).items()
            if _to_float(cost) is not None
        }
    if cost_applies and matched_plan:
        for item in matched_plan.get("line_items") or []:
            strategy_id = _strategy_id(item)
            cost = _to_float(item.get("estimated_transaction_cost")) or 0.0
            if strategy_id:
                cost_by_strategy[strategy_id] = cost
    total_cost = (
        sum(cost_by_strategy.values())
        if cost_by_strategy
        else (_to_float(target.get("paper_transaction_cost_total")) or 0.0 if cost_applies else 0.0)
    )
    return {
        "applied": True,
        "weights": {
            str(strategy_id): float(weight)
            for strategy_id, weight in (target.get("weights") or {}).items()
            if _to_float(weight) is not None
        },
        "transaction_cost_total": total_cost,
        "cost_by_strategy": cost_by_strategy,
        "applied_plan_id": plan_id,
        "intended_effective_date": intended_effective_date,
        "cost_applies_to_trading_date": cost_applies,
        "persistence_note": (
            "Paper target/cost artifacts are local filesystem persistence; hosted services without durable disk "
            "must externalize these artifacts before treating next-day persistence as guaranteed."
        ),
    }


def _is_business_day(value: str) -> bool:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return parsed.weekday() < 5


def _paper_backfill_warning(source_row: dict[str, Any]) -> str:
    label = source_row.get("record_label") or "canonical_portfolio_daily"
    return (
        "paper performance backfill seeded from canonical portfolio_daily "
        f"portfolio-level row ({label}); official ledger remains separate; "
        "not regenerated from historical ticker prices"
    )


def build_paper_portfolio_backfill_rows(
    canonical: dict[str, Any],
    *,
    start_date: str = "2026-06-04",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_row in canonical.get("portfolio_daily") or []:
        trading_date = str(source_row.get("date") or source_row.get("trading_date") or "")
        if not trading_date or trading_date < start_date or not _is_business_day(trading_date):
            continue
        prior_nav = _to_float(source_row.get("beginning_nav"))
        nav = _to_float(source_row.get("ending_nav") or source_row.get("nav"))
        daily_pnl = _to_float(source_row.get("net_pnl") or source_row.get("daily_pnl"))
        daily_return = _to_float(source_row.get("daily_return"))
        if prior_nav is None or nav is None or daily_pnl is None or daily_return is None:
            continue
        rows.append(
            {
                "date": trading_date,
                "trading_date": trading_date,
                "as_of_time": source_row.get("data_as_of") or trading_date,
                "source": "canonical_operational_portfolio_daily_paper_backfill",
                "source_artifact": "dashboard/data/canonical_operational.json",
                "source_record_label": source_row.get("record_label"),
                "position_source": "committed_shadow_holdings",
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
                "market_data_provider": "canonical_operational_snapshot",
                "provider": "canonical_operational_snapshot",
                "prior_nav": prior_nav,
                "beginning_nav": prior_nav,
                "nav": nav,
                "ending_nav": nav,
                "daily_pnl": daily_pnl,
                "net_pnl": daily_pnl,
                "daily_return": daily_return,
                "refresh_status": "backfilled_from_canonical_portfolio_daily",
                "ticker_count_requested": None,
                "ticker_count_successful": None,
                "covered_weight": None,
                "priced_tickers": [],
                "missing_tickers": [],
                "stale_tickers": [],
                "warnings": [_paper_backfill_warning(source_row)],
            }
        )
    return rows


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _business_dates_between(start: str, end: str, holidays: list[str] | set[str] | None = None) -> list[str]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None or start_date > end_date:
        return []
    holiday_set = {str(item)[:10] for item in (holidays or [])}
    rows: list[str] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5 and current.isoformat() not in holiday_set:
            rows.append(current.isoformat())
        current = current + timedelta(days=1)
    return rows


def missing_paper_portfolio_business_dates(
    existing_rows: list[dict[str, Any]],
    *,
    through_date: str,
    holidays: list[str] | set[str] | None = None,
    include_through_date: bool = False,
) -> list[str]:
    """Find trading-day holes already inside the paper ledger date window."""
    existing_dates = {
        str(row.get("date") or row.get("trading_date") or "")[:10]
        for row in existing_rows
        if row.get("date") or row.get("trading_date")
    }
    if not existing_dates or not through_date:
        return []
    start_date = min(existing_dates)
    candidate_dates = _business_dates_between(start_date, str(through_date)[:10], holidays)
    return [
        row_date
        for row_date in candidate_dates
        if row_date not in existing_dates and (include_through_date or row_date < str(through_date)[:10])
    ]


def _latest_holding_rows(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    holdings = canonical.get("holdings") or []
    latest_date = max((str(row.get("date") or "") for row in holdings), default="")
    return [deepcopy(row) for row in holdings if row.get("date") == latest_date and row.get("ticker")]


def _price_lookup(price_history: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    lookup: dict[tuple[str, str], float] = {}
    for row in price_history:
        ticker = str(row.get("ticker") or "")
        row_date = str(row.get("date") or "")
        close = _to_float(row.get("close") or row.get("adj_close"))
        if ticker and row_date and close is not None:
            lookup[(ticker, row_date)] = close
    return lookup


def _price_history_rows(fetch_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (
        fetch_result.get("daily_price_history")
        or fetch_result.get("price_history")
        or fetch_result.get("market_proxy_price_history")
        or []
    )
    return rows if isinstance(rows, list) else []


def _first_missing_business_date(start_date: str, existing_dates: set[str], through_date: str) -> str | None:
    for row_date in _business_dates_between(start_date, through_date):
        if row_date not in existing_dates:
            return row_date
    return None


def build_paper_portfolio_backfill_rows_from_price_history(
    canonical: dict[str, Any],
    price_history: list[dict[str, Any]],
    *,
    start_date: str = "2026-06-04",
    through_date: str | None = None,
) -> list[dict[str, Any]]:
    canonical_rows = build_paper_portfolio_backfill_rows(canonical, start_date=start_date)
    price_dates = sorted({str(row.get("date") or "") for row in price_history if row.get("date")})
    latest_price_date = through_date or (price_dates[-1] if price_dates else None)
    if not latest_price_date:
        return canonical_rows
    canonical_dates = {row["date"] for row in canonical_rows}
    first_gap = _first_missing_business_date(start_date, canonical_dates, latest_price_date)
    if first_gap is None:
        seed_rows = canonical_rows
        estimate_start = None
    else:
        seed_rows = [row for row in canonical_rows if row["date"] < first_gap]
        estimate_start = first_gap
    if estimate_start is None:
        return seed_rows
    if not seed_rows:
        return []

    holdings = _latest_holding_rows(canonical)
    prices = _price_lookup(price_history)
    portfolio_dates = _business_dates_between(start_date, latest_price_date)
    estimate_dates = [row_date for row_date in portfolio_dates if row_date >= estimate_start]
    rows = [deepcopy(row) for row in seed_rows]
    prior_nav = _to_float(rows[-1].get("ending_nav") or rows[-1].get("nav"))
    if prior_nav is None:
        return rows
    peak = max((_to_float(row.get("ending_nav") or row.get("nav")) or prior_nav for row in rows), default=prior_nav)
    first_nav = _to_float(rows[0].get("beginning_nav") or rows[0].get("prior_nav")) or prior_nav

    for row_date in estimate_dates:
        date_index = portfolio_dates.index(row_date)
        if date_index == 0:
            continue
        previous_date = portfolio_dates[date_index - 1]
        daily_pnl = 0.0
        priced_positions = 0
        missing_tickers: set[str] = set()
        priced_tickers: set[str] = set()
        for holding in holdings:
            ticker = str(holding.get("ticker") or "")
            quantity = _to_float(holding.get("simulated_quantity"))
            previous_close = prices.get((ticker, previous_date))
            close = prices.get((ticker, row_date))
            if not ticker or quantity is None or previous_close is None or close is None:
                if ticker:
                    missing_tickers.add(ticker)
                continue
            daily_pnl += quantity * (close - previous_close)
            priced_positions += 1
            priced_tickers.add(ticker)
        if priced_positions == 0:
            continue
        nav = prior_nav + daily_pnl
        peak = max(peak, nav)
        warning = (
            "current holdings paper estimate backfill uses latest committed holdings for historical "
            "missing dates; delayed yfinance daily closes; not official ledger"
        )
        if missing_tickers:
            warning += f"; partial price coverage missing {len(missing_tickers)} tickers"
        row = {
            "date": row_date,
            "trading_date": row_date,
            "as_of_time": row_date,
            "source": "current_holdings_paper_estimate_backfill",
            "source_artifact": "dashboard/data/canonical_operational.json + delayed_yfinance_daily_close",
            "position_source": "committed_shadow_holdings",
            "paper_only": True,
            "delayed_market_data": True,
            "not_live_market_data": True,
            "live_brokerage_execution": False,
            "is_official_ledger": False,
            "market_data_provider": "yfinance",
            "provider": "yfinance",
            "prior_nav": prior_nav,
            "beginning_nav": prior_nav,
            "nav": nav,
            "ending_nav": nav,
            "daily_pnl": daily_pnl,
            "net_pnl": daily_pnl,
            "daily_return": daily_pnl / prior_nav if prior_nav else None,
            "cumulative_pnl": nav - first_nav,
            "cumulative_return": nav / first_nav - 1 if first_nav else None,
            "running_peak": peak,
            "current_drawdown": nav / peak - 1 if peak else None,
            "refresh_status": "backfilled_from_current_holdings_delayed_close",
            "ticker_count_requested": len({row.get("ticker") for row in holdings if row.get("ticker")}),
            "ticker_count_successful": len(priced_tickers),
            "covered_weight": None,
            "priced_tickers": sorted(priced_tickers),
            "missing_tickers": sorted(missing_tickers),
            "stale_tickers": [],
            "warnings": [warning],
        }
        rows.append(row)
        prior_nav = nav
    return rows


def write_paper_portfolio_daily_rows(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] | None = None
    for row in rows:
        payload = upsert_paper_portfolio_daily(root, row)
    if payload is None:
        return paper_portfolio_snapshot_payload(root, limit=10_000)
    return payload


def backfill_paper_portfolio_daily_from_canonical(
    root: Path,
    canonical: dict[str, Any],
    *,
    start_date: str = "2026-06-04",
) -> dict[str, Any]:
    payload: dict[str, Any] | None = None
    for row in build_paper_portfolio_backfill_rows(canonical, start_date=start_date):
        payload = upsert_paper_portfolio_daily(root, row)
    if payload is None:
        return paper_portfolio_snapshot_payload(root, limit=10_000)
    return payload


def build_paper_portfolio_daily_row(
    artifact: dict[str, Any],
    fetch_result: dict[str, Any],
    *,
    refresh_status: str,
    warnings: list[str] | None = None,
    position_source: str = "committed_shadow_holdings",
    rebalance: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    rebalance = rebalance or {}
    applied_weights = rebalance.get("weights") or {}
    bars = {
        str(row.get("source_ticker") or row.get("ticker")): row
        for row in fetch_result.get("rows") or []
        if row.get("source_ticker") or row.get("ticker")
    }
    if not bars:
        return None
    strategy_rows = artifact.get("strategies") or []
    portfolio_return = 0.0
    covered_weight = 0.0
    priced_tickers: set[str] = set()
    for strategy in strategy_rows:
        strategy_id = str(strategy.get("strategy_id") or strategy.get("internal_id") or "")
        strategy_weight = _to_float(strategy.get("current_weight"))
        if strategy_weight is None:
            strategy_weight = _to_float(
                (artifact.get("allocation") or {}).get("current_weights", {}).get(strategy_id)
            )
        applied_weight = _to_float(applied_weights.get(strategy_id))
        if applied_weight is not None:
            strategy_weight = applied_weight
        if strategy_weight is None or strategy_weight == 0:
            continue
        for position in (strategy.get("position_packet") or {}).get("latest_positions") or []:
            ticker = str(position.get("source_ticker") or position.get("ticker") or "")
            if not ticker:
                continue
            bar = bars.get(ticker)
            position_return = _to_float((bar or {}).get("intraday_return_from_open"))
            position_weight = _to_float(position.get("weight"))
            if position_return is None or position_weight is None:
                continue
            aggregate_weight = strategy_weight * position_weight
            portfolio_return += aggregate_weight * position_return
            covered_weight += abs(aggregate_weight)
            priced_tickers.add(ticker)
    if covered_weight == 0:
        return None
    prior_nav = _to_float(artifact.get("initial_capital")) or 1_000_000.0
    daily_pnl = prior_nav * portfolio_return
    nav = prior_nav + daily_pnl
    trading_date = (
        fetch_result.get("market_session_date")
        or fetch_result.get("session_date")
        or _latest_date([row for row in fetch_result.get("rows") or [] if row.get("session_date")])
        or (str(fetch_result.get("latest_completed_bar_ts_et") or fetch_result.get("latest_observation_ts_et") or "")[:10])
    )
    if not trading_date:
        return None
    transaction_cost = _to_float(rebalance.get("transaction_cost_total")) or 0.0
    net_pnl = daily_pnl - transaction_cost
    nav = prior_nav + net_pnl
    return {
        "date": trading_date,
        "trading_date": trading_date,
        "as_of_time": fetch_result.get("latest_completed_bar_ts_et") or fetch_result.get("latest_observation_ts_et"),
        "source": "Paper Portfolio Daily Ledger",
        "source_artifact": str(PAPER_PORTFOLIO_DAILY_RELATIVE_PATH).replace("\\", "/"),
        "position_source": position_source,
        "paper_only": True,
        "delayed_market_data": True,
        "not_live_market_data": True,
        "live_brokerage_execution": False,
        "is_official_ledger": False,
        "provider": fetch_result.get("provider"),
        "prior_nav": prior_nav,
        "beginning_nav": prior_nav,
        "nav": nav,
        "ending_nav": nav,
        "gross_pnl": daily_pnl,
        "paper_transaction_cost": transaction_cost,
        "transaction_cost": transaction_cost,
        "daily_pnl": net_pnl,
        "net_pnl": net_pnl,
        "daily_return": net_pnl / prior_nav if prior_nav else None,
        "refresh_status": refresh_status,
        "ticker_count_requested": int(fetch_result.get("ticker_count_requested") or len(bars)),
        "ticker_count_successful": int(fetch_result.get("ticker_count_successful") or len(priced_tickers)),
        "covered_weight": covered_weight,
        "priced_tickers": sorted(priced_tickers),
        "missing_tickers": fetch_result.get("missing_tickers") or [],
        "stale_tickers": fetch_result.get("stale_tickers") or [],
        "warnings": warnings or [],
        "applied_paper_rebalance_plan_id": rebalance.get("applied_plan_id"),
        "paper_rebalance_cost_included": transaction_cost > 0,
        "applied_paper_allocation": {
            "applied": bool(rebalance.get("applied")),
            "weights": rebalance.get("weights") or {},
            "intended_effective_date": rebalance.get("intended_effective_date"),
            "persistence_note": rebalance.get("persistence_note"),
        },
    }


def build_paper_portfolio_gap_fill_rows(
    artifact: dict[str, Any],
    fetch_result: dict[str, Any],
    *,
    existing_rows: list[dict[str, Any]],
    through_date: str,
    holidays: list[str] | set[str] | None = None,
    position_source: str = "committed_shadow_holdings",
    rebalance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fill missing paper ledger trading days using delayed daily close history."""
    price_history = _price_history_rows(fetch_result)
    if not price_history:
        return []
    missing_dates = missing_paper_portfolio_business_dates(
        existing_rows,
        through_date=through_date,
        holidays=holidays,
    )
    if not missing_dates:
        return []

    prices = _price_lookup(price_history)
    price_dates = sorted({row_date for _, row_date in prices})
    if not price_dates:
        return []

    rebalance = rebalance or {}
    applied_weights = rebalance.get("weights") or {}
    generated: list[dict[str, Any]] = []
    first_existing = sorted(
        [deepcopy(row) for row in existing_rows if row.get("date")],
        key=lambda row: str(row.get("date") or ""),
    )
    first_nav = (
        _to_float((first_existing[0] if first_existing else {}).get("beginning_nav"))
        or _to_float((first_existing[0] if first_existing else {}).get("prior_nav"))
        or _to_float(artifact.get("initial_capital"))
        or 1_000_000.0
    )
    provider = fetch_result.get("daily_price_history_provider") or fetch_result.get("provider") or "yfinance"

    for row_date in missing_dates:
        prior_candidates = [
            row for row in [*first_existing, *generated]
            if str(row.get("date") or "") < row_date
        ]
        if not prior_candidates:
            continue
        prior_row = sorted(prior_candidates, key=lambda row: str(row.get("date") or ""))[-1]
        prior_nav = _to_float(prior_row.get("ending_nav") or prior_row.get("nav"))
        if prior_nav is None:
            continue
        previous_price_date = max((price_date for price_date in price_dates if price_date < row_date), default=None)
        if previous_price_date is None:
            continue

        portfolio_return = 0.0
        covered_weight = 0.0
        requested_tickers: set[str] = set()
        priced_tickers: set[str] = set()
        missing_tickers: set[str] = set()
        for strategy in artifact.get("strategies") or []:
            strategy_id = str(strategy.get("strategy_id") or strategy.get("internal_id") or "")
            strategy_weight = _to_float(strategy.get("current_weight"))
            if strategy_weight is None:
                strategy_weight = _to_float((artifact.get("allocation") or {}).get("current_weights", {}).get(strategy_id))
            applied_weight = _to_float(applied_weights.get(strategy_id))
            if applied_weight is not None:
                strategy_weight = applied_weight
            if strategy_weight is None or strategy_weight == 0:
                continue
            for position in (strategy.get("position_packet") or {}).get("latest_positions") or []:
                ticker = str(position.get("source_ticker") or position.get("ticker") or "")
                position_weight = _to_float(position.get("weight"))
                if not ticker or position_weight is None:
                    continue
                requested_tickers.add(ticker)
                previous_close = prices.get((ticker, previous_price_date))
                close = prices.get((ticker, row_date))
                if previous_close is None or close is None or previous_close == 0:
                    missing_tickers.add(ticker)
                    continue
                aggregate_weight = strategy_weight * position_weight
                portfolio_return += aggregate_weight * (close / previous_close - 1.0)
                covered_weight += abs(aggregate_weight)
                priced_tickers.add(ticker)
        if covered_weight == 0:
            continue

        daily_pnl = prior_nav * portfolio_return
        nav = prior_nav + daily_pnl
        prior_peak = max(
            (
                _to_float(row.get("ending_nav") or row.get("nav")) or prior_nav
                for row in [*first_existing, *generated]
                if str(row.get("date") or "") < row_date
            ),
            default=prior_nav,
        )
        peak = max(prior_peak, nav)
        warning = (
            "paper daily gap fill uses delayed daily close history for a missing trading day; "
            "official ledger remains separate; not live brokerage execution"
        )
        if missing_tickers:
            warning += f"; partial price coverage missing {len(missing_tickers)} tickers"
        generated.append(
            {
                "date": row_date,
                "trading_date": row_date,
                "as_of_time": row_date,
                "source": "Paper Portfolio Daily Gap Fill",
                "source_artifact": str(PAPER_PORTFOLIO_DAILY_RELATIVE_PATH).replace("\\", "/"),
                "position_source": position_source,
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
                "market_data_provider": provider,
                "provider": provider,
                "prior_nav": prior_nav,
                "beginning_nav": prior_nav,
                "nav": nav,
                "ending_nav": nav,
                "gross_pnl": daily_pnl,
                "paper_transaction_cost": 0.0,
                "transaction_cost": 0.0,
                "daily_pnl": daily_pnl,
                "net_pnl": daily_pnl,
                "daily_return": daily_pnl / prior_nav if prior_nav else None,
                "cumulative_pnl": nav - first_nav,
                "cumulative_return": nav / first_nav - 1 if first_nav else None,
                "running_peak": peak,
                "current_drawdown": nav / peak - 1 if peak else None,
                "refresh_status": "gap_filled_from_delayed_daily_close",
                "ticker_count_requested": len(requested_tickers),
                "ticker_count_successful": len(priced_tickers),
                "covered_weight": covered_weight,
                "priced_tickers": sorted(priced_tickers),
                "missing_tickers": sorted(missing_tickers),
                "stale_tickers": [],
                "price_history_previous_date": previous_price_date,
                "warnings": [warning],
                "applied_paper_rebalance_plan_id": rebalance.get("applied_plan_id"),
                "paper_rebalance_cost_included": False,
                "applied_paper_allocation": {
                    "applied": bool(rebalance.get("applied")),
                    "weights": rebalance.get("weights") or {},
                    "intended_effective_date": rebalance.get("intended_effective_date"),
                    "persistence_note": rebalance.get("persistence_note"),
                },
            }
        )
    return generated


def rebase_paper_portfolio_daily_row(row: dict[str, Any], prior_nav: float | None) -> dict[str, Any]:
    """Rebase a current-session paper row so NAV delta matches its daily P&L."""
    if prior_nav is None:
        return deepcopy(row)
    rebased = deepcopy(row)
    old_prior = _to_float(rebased.get("prior_nav") or rebased.get("beginning_nav")) or prior_nav
    transaction_cost = _to_float(rebased.get("paper_transaction_cost") or rebased.get("transaction_cost")) or 0.0
    gross_pnl = _to_float(rebased.get("gross_pnl"))
    net_pnl = _to_float(rebased.get("daily_pnl") or rebased.get("net_pnl"))
    if gross_pnl is not None and old_prior:
        gross_return = gross_pnl / old_prior
        gross_pnl = prior_nav * gross_return
        net_pnl = gross_pnl - transaction_cost
    elif net_pnl is not None and old_prior:
        net_return = net_pnl / old_prior
        net_pnl = prior_nav * net_return
        gross_pnl = net_pnl + transaction_cost
    else:
        return rebased
    nav = prior_nav + net_pnl
    rebased.update(
        {
            "prior_nav": prior_nav,
            "beginning_nav": prior_nav,
            "gross_pnl": gross_pnl,
            "paper_transaction_cost": transaction_cost,
            "transaction_cost": transaction_cost,
            "daily_pnl": net_pnl,
            "net_pnl": net_pnl,
            "daily_return": net_pnl / prior_nav if prior_nav else None,
            "nav": nav,
            "ending_nav": nav,
            "paper_nav_rebased_to_previous_paper_close": True,
        }
    )
    return rebased


def build_paper_strategy_daily_rows(
    artifact: dict[str, Any],
    fetch_result: dict[str, Any],
    *,
    refresh_status: str,
    position_source: str = "committed_shadow_holdings",
    rebalance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    bars = {
        str(row.get("source_ticker") or row.get("ticker")): row
        for row in fetch_result.get("rows") or []
        if row.get("source_ticker") or row.get("ticker")
    }
    if not bars:
        return []
    rebalance = rebalance or {}
    cost_by_strategy = rebalance.get("cost_by_strategy") or {}
    applied_weights = rebalance.get("weights") or {}
    prior_portfolio_nav = _to_float(artifact.get("initial_capital")) or 1_000_000.0
    trading_date = (
        fetch_result.get("market_session_date")
        or fetch_result.get("session_date")
        or _latest_date([row for row in fetch_result.get("rows") or [] if row.get("session_date")])
        or (str(fetch_result.get("latest_completed_bar_ts_et") or fetch_result.get("latest_observation_ts_et") or "")[:10])
    )
    if not trading_date:
        return []
    rows: list[dict[str, Any]] = []
    for strategy in artifact.get("strategies") or []:
        strategy_id = str(strategy.get("strategy_id") or strategy.get("internal_id") or "")
        if not strategy_id:
            continue
        strategy_weight = _to_float(strategy.get("current_weight"))
        if strategy_weight is None:
            strategy_weight = _to_float((artifact.get("allocation") or {}).get("current_weights", {}).get(strategy_id))
        if strategy_weight is None or strategy_weight == 0:
            continue
        strategy_return = 0.0
        covered = 0
        total = 0
        for position in (strategy.get("position_packet") or {}).get("latest_positions") or []:
            ticker = str(position.get("source_ticker") or position.get("ticker") or "")
            if not ticker:
                continue
            total += 1
            position_return = _to_float((bars.get(ticker) or {}).get("intraday_return_from_open"))
            position_weight = _to_float(position.get("weight"))
            if position_return is None or position_weight is None:
                continue
            covered += 1
            strategy_return += position_weight * position_return
        if covered == 0 or total == 0:
            continue
        applied_weight = _to_float(applied_weights.get(strategy_id))
        effective_weight = applied_weight if applied_weight is not None else strategy_weight
        prior_nav = prior_portfolio_nav * effective_weight
        gross_pnl = prior_nav * strategy_return
        transaction_cost = _to_float(cost_by_strategy.get(strategy_id)) or 0.0
        net_pnl = gross_pnl - transaction_cost
        rows.append(
            {
                "date": trading_date,
                "trading_date": trading_date,
                "strategy_id": strategy_id,
                "display_name": strategy.get("name") or strategy.get("display_name") or strategy_id,
                "as_of_time": fetch_result.get("latest_completed_bar_ts_et") or fetch_result.get("latest_observation_ts_et"),
                "source": "Paper Strategy Daily Ledger",
                "source_artifact": str(PAPER_STRATEGY_DAILY_RELATIVE_PATH).replace("\\", "/"),
                "position_source": position_source,
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
                "provider": fetch_result.get("provider"),
                "prior_nav": prior_nav,
                "beginning_nav": prior_nav,
                "gross_pnl": gross_pnl,
                "paper_transaction_cost": transaction_cost,
                "transaction_cost": transaction_cost,
                "daily_pnl": net_pnl,
                "net_pnl": net_pnl,
                "daily_return": net_pnl / prior_nav if prior_nav else None,
                "nav": prior_nav + net_pnl,
                "ending_nav": prior_nav + net_pnl,
                "refresh_status": refresh_status,
                "price_coverage": {
                    "priced": covered,
                    "total": total,
                    "status": "COMPLETE" if covered == total else "PARTIAL",
                },
                "latest_delayed_price_as_of": fetch_result.get("latest_completed_bar_ts_et") or fetch_result.get("latest_observation_ts_et"),
                "applied_paper_target_weight": applied_weights.get(strategy_id),
                "applied_paper_rebalance_plan_id": rebalance.get("applied_plan_id"),
                "paper_rebalance_cost_included": transaction_cost > 0,
            }
        )
    return rows


def upsert_paper_portfolio_daily(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    path = paper_portfolio_daily_path(root)
    payload = _read_json(
        path,
        {
            "schema_version": PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
            "metadata": {
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
                "position_source": "committed_shadow_holdings",
            },
            "rows": [],
        },
    )
    rows = [deepcopy(item) for item in payload.get("rows") or [] if item.get("date")]
    rows = [item for item in rows if item.get("date") != row.get("date")]
    rows.append(deepcopy(row))
    rows.sort(key=lambda item: str(item.get("date") or ""))
    peak = None
    for item in rows:
        nav = _to_float(item.get("ending_nav") or item.get("nav"))
        if nav is None:
            item["running_peak"] = None
            item["current_drawdown"] = None
            item["cumulative_pnl"] = None
            item["cumulative_return"] = None
            continue
        peak = nav if peak is None else max(peak, nav)
        first_nav = _to_float(rows[0].get("beginning_nav") or rows[0].get("prior_nav")) or nav
        item["running_peak"] = peak
        item["current_drawdown"] = nav / peak - 1 if peak else None
        item["cumulative_pnl"] = nav - first_nav
        item["cumulative_return"] = nav / first_nav - 1 if first_nav else None
    metadata = {
        **(payload.get("metadata") or {}),
        "schema_version": PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
        "row_count": len(rows),
        "latest_date": rows[-1].get("date") if rows else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "delayed_market_data": True,
        "not_live_market_data": True,
        "live_brokerage_execution": False,
        "is_official_ledger": False,
        "position_source": row.get("position_source") or "committed_shadow_holdings",
    }
    next_payload = {
        "schema_version": PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
        "metadata": metadata,
        "rows": rows,
    }
    _atomic_write_json(path, next_payload)
    return next_payload


def upsert_paper_strategy_daily(root: Path, rows_to_upsert: list[dict[str, Any]]) -> dict[str, Any]:
    path = paper_strategy_daily_path(root)
    payload = _read_json(
        path,
        {
            "schema_version": PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
            "metadata": {
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
                "position_source": "committed_shadow_holdings",
            },
            "rows": [],
        },
    )
    incoming = [deepcopy(row) for row in rows_to_upsert if row.get("date") and _strategy_id(row)]
    existing = [
        deepcopy(row)
        for row in payload.get("rows") or []
        if row.get("date") and _strategy_id(row)
    ]
    incoming_keys = {(row["date"], _strategy_id(row)) for row in incoming}
    rows = [
        row for row in existing
        if (row.get("date"), _strategy_id(row)) not in incoming_keys
    ]
    rows.extend(incoming)
    rows.sort(key=lambda item: (str(item.get("date") or ""), str(_strategy_id(item) or "")))
    metadata = {
        **(payload.get("metadata") or {}),
        "schema_version": PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
        "row_count": len(rows),
        "latest_date": rows[-1].get("date") if rows else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "delayed_market_data": True,
        "not_live_market_data": True,
        "live_brokerage_execution": False,
        "is_official_ledger": False,
    }
    next_payload = {
        "schema_version": PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
        "metadata": metadata,
        "rows": rows,
    }
    _atomic_write_json(path, next_payload)
    return next_payload


def paper_portfolio_snapshot_payload(root: Path, *, limit: int = 20) -> dict[str, Any]:
    payload = _read_json(
        paper_portfolio_daily_path(root),
        {
            "schema_version": PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
            "metadata": {
                "schema_version": PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
                "row_count": 0,
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
                "position_source": "committed_shadow_holdings",
            },
            "rows": [],
        },
    )
    rows = sorted([deepcopy(row) for row in payload.get("rows") or []], key=lambda row: str(row.get("date") or ""))
    return {
        "schema_version": payload.get("schema_version") or PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
        "metadata": {
            **(payload.get("metadata") or {}),
            "schema_version": payload.get("schema_version") or PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION,
            "row_count": len(rows),
            "paper_only": True,
            "delayed_market_data": True,
            "not_live_market_data": True,
            "live_brokerage_execution": False,
            "is_official_ledger": False,
        },
        "rows": rows[-limit:],
    }


def paper_strategy_snapshot_payload(root: Path, *, limit: int = 10_000) -> dict[str, Any]:
    payload = _read_json(
        paper_strategy_daily_path(root),
        {
            "schema_version": PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
            "metadata": {
                "schema_version": PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
                "row_count": 0,
                "paper_only": True,
                "delayed_market_data": True,
                "not_live_market_data": True,
                "live_brokerage_execution": False,
                "is_official_ledger": False,
            },
            "rows": [],
        },
    )
    rows = sorted(
        [deepcopy(row) for row in payload.get("rows") or []],
        key=lambda row: (str(row.get("date") or ""), str(_strategy_id(row) or "")),
    )
    return {
        "schema_version": payload.get("schema_version") or PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
        "metadata": {
            **(payload.get("metadata") or {}),
            "schema_version": payload.get("schema_version") or PAPER_STRATEGY_DAILY_SCHEMA_VERSION,
            "row_count": len(rows),
            "paper_only": True,
            "delayed_market_data": True,
            "not_live_market_data": True,
            "live_brokerage_execution": False,
            "is_official_ledger": False,
        },
        "rows": rows[-limit:],
    }
