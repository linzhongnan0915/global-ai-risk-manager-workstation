from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PAPER_PORTFOLIO_DAILY_RELATIVE_PATH = Path("dashboard/data/performance/paper_portfolio_daily.json")
PAPER_PORTFOLIO_DAILY_SCHEMA_VERSION = "paper_portfolio_daily_v1"


def paper_portfolio_daily_path(root: Path) -> Path:
    return root / PAPER_PORTFOLIO_DAILY_RELATIVE_PATH


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


def build_paper_portfolio_daily_row(
    artifact: dict[str, Any],
    fetch_result: dict[str, Any],
    *,
    refresh_status: str,
    warnings: list[str] | None = None,
    position_source: str = "committed_shadow_holdings",
) -> dict[str, Any] | None:
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
        strategy_weight = _to_float(strategy.get("current_weight"))
        if strategy_weight is None:
            strategy_weight = _to_float(
                (artifact.get("allocation") or {}).get("current_weights", {}).get(strategy.get("strategy_id"))
            )
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
        "daily_pnl": daily_pnl,
        "net_pnl": daily_pnl,
        "daily_return": portfolio_return,
        "refresh_status": refresh_status,
        "ticker_count_requested": int(fetch_result.get("ticker_count_requested") or len(bars)),
        "ticker_count_successful": int(fetch_result.get("ticker_count_successful") or len(priced_tickers)),
        "covered_weight": covered_weight,
        "priced_tickers": sorted(priced_tickers),
        "missing_tickers": fetch_result.get("missing_tickers") or [],
        "stale_tickers": fetch_result.get("stale_tickers") or [],
        "warnings": warnings or [],
    }


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
