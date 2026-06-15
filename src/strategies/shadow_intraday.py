"""Intraday estimates and idempotent daily finalization for retained shadow strategies."""

from __future__ import annotations

from datetime import datetime, timedelta, time
from pathlib import Path
import sqlite3
from typing import Any

MEMBER_IDS = ("C2A2_020", "C2B2_004")
COMPOSITE_ID = "STRATEGY_21_RESEARCH_COMPOSITE_V1"
COMPOSITE_WEIGHTS = {"C2A2_020": 0.5, "C2B2_004": 0.5}
INTRADAY_LABEL = "INTRADAY_SHADOW_ESTIMATE"
DAILY_LABEL = "DAILY_SHADOW_RETURN"


def latest_shadow_positions(database_path: str | Path) -> dict[str, dict[str, float]]:
    path = Path(database_path)
    if not path.exists():
        return {}
    positions: dict[str, dict[str, float]] = {}
    with sqlite3.connect(path) as connection:
        for strategy_id in MEMBER_IDS:
            latest = connection.execute(
                "SELECT MAX(date) FROM daily_strategy_positions WHERE strategy_id=? AND data_label='SHADOW'",
                (strategy_id,),
            ).fetchone()[0]
            if latest:
                positions[strategy_id] = dict(
                    connection.execute(
                        "SELECT ticker, target_weight FROM daily_strategy_positions "
                        "WHERE strategy_id=? AND date=? AND data_label='SHADOW'",
                        (strategy_id, latest),
                    )
                )
    return positions


def collect_shadow_position_tickers(database_path: str | Path) -> list[str]:
    return sorted({ticker for positions in latest_shadow_positions(database_path).values() for ticker in positions})


def daily_shadow_return_exists(database_path: str | Path, session_date: str) -> bool:
    path = Path(database_path)
    if not path.exists():
        return False
    with sqlite3.connect(path) as connection:
        return bool(
            connection.execute(
                "SELECT 1 FROM daily_strategy_returns WHERE strategy_id=? AND date=? AND data_label=?",
                (COMPOSITE_ID, session_date, DAILY_LABEL),
            ).fetchone()
        )


def build_shadow_intraday_estimates(
    database_path: str | Path, rows: list[dict[str, Any]], *, notional: float = 1_000_000.0,
) -> dict[str, Any]:
    completed = [row for row in rows if row.get("bar_completeness") == "completed"] or rows
    if not completed:
        return {
            "data_label": INTRADAY_LABEL, "available": False, "strategies": [],
            "session_date": None, "estimated_pnl": None, "estimated_return": None,
        }
    session_date = max(row["session_date"] for row in completed)
    session_rows = [row for row in completed if row["session_date"] == session_date]
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in session_rows:
        by_ticker.setdefault(row["source_ticker"], []).append(row)
    moves = {}
    latest_prices = {}
    for ticker, ticker_rows in by_ticker.items():
        ordered = sorted(ticker_rows, key=lambda item: item["observation_ts_et"])
        first_open = ordered[0].get("open")
        latest = ordered[-1]
        if first_open and latest.get("close") is not None:
            moves[ticker] = float(latest["close"]) / float(first_open) - 1.0
            latest_prices[ticker] = {"price": latest["close"], "timestamp": latest["observation_ts_et"]}
    strategy_rows = []
    for strategy_id, positions in latest_shadow_positions(database_path).items():
        missing = sorted(ticker for ticker in positions if ticker not in moves)
        uncovered = sum(abs(float(positions[ticker])) for ticker in missing)
        available = bool(positions) and not missing
        strategy_return = sum(float(weight) * moves[ticker] for ticker, weight in positions.items()) if available else None
        strategy_rows.append(
            {
                "strategy_id": strategy_id, "available": available,
                "status": "COMPLETE" if available else "INCOMPLETE",
                "estimated_return": strategy_return,
                "estimated_pnl": notional * strategy_return if strategy_return is not None else None,
                "missing_tickers": missing, "uncovered_gross_weight": uncovered,
            }
        )
    member_lookup = {row["strategy_id"]: row for row in strategy_rows}
    component_complete = all(member_lookup.get(key, {}).get("available") for key in COMPOSITE_WEIGHTS)
    composite_return = (
        sum(COMPOSITE_WEIGHTS[key] * member_lookup[key]["estimated_return"] for key in COMPOSITE_WEIGHTS)
        if component_complete else None
    )
    strategy_rows.append(
        {
            "strategy_id": COMPOSITE_ID, "available": component_complete,
            "status": "COMPLETE" if component_complete else "INCOMPLETE",
            "estimated_return": composite_return,
            "estimated_pnl": notional * composite_return if composite_return is not None else None,
            "missing_tickers": sorted({
                ticker for key in COMPOSITE_WEIGHTS for ticker in member_lookup.get(key, {}).get("missing_tickers", [])
            }),
            "uncovered_gross_weight": sum(
                COMPOSITE_WEIGHTS[key] * member_lookup.get(key, {}).get("uncovered_gross_weight", 0.0)
                for key in COMPOSITE_WEIGHTS
            ),
        }
    )
    return {
        "data_label": INTRADAY_LABEL,
        "available": component_complete,
        "estimated_return": composite_return,
        "estimated_pnl": notional * composite_return if composite_return is not None else None,
        "session_date": session_date,
        "strategies": strategy_rows,
        "latest_usable_prices": latest_prices,
    }


def finalize_daily_shadow_returns(
    database_path: str | Path, estimates: dict[str, Any], *, latest_completed_bar_ts: str | None, bar_minutes: int,
) -> dict[str, Any]:
    if not latest_completed_bar_ts or not estimates.get("session_date"):
        return {"finalized": False, "reason": "no_completed_bar"}
    bar_end = datetime.fromisoformat(latest_completed_bar_ts) + timedelta(minutes=bar_minutes)
    if bar_end.time() < time(16, 0):
        return {"finalized": False, "reason": "session_not_complete"}
    path = Path(database_path)
    if not path.exists():
        return {"finalized": False, "reason": "shadow_database_missing"}
    session_date = estimates["session_date"]
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_strategy_returns)")}
        if "nav_value" not in columns:
            connection.execute("ALTER TABLE daily_strategy_returns ADD COLUMN nav_value REAL")
        available_rows = [row for row in estimates.get("strategies") or [] if row.get("available")]
        for row in available_rows:
            prior = connection.execute(
                "SELECT nav_value FROM daily_strategy_returns WHERE strategy_id=? AND data_label=? "
                "AND date<? ORDER BY date DESC LIMIT 1",
                (row["strategy_id"], DAILY_LABEL, session_date),
            ).fetchone()
            prior_nav = float(prior[0]) if prior and prior[0] is not None else 1.0
            daily_return = float(row["estimated_return"])
            connection.execute(
                "INSERT OR REPLACE INTO daily_strategy_returns "
                "(strategy_id,date,data_label,net_return,nav_value) VALUES (?,?,?,?,?)",
                (row["strategy_id"], session_date, DAILY_LABEL, daily_return, prior_nav * (1.0 + daily_return)),
            )
        connection.commit()
    return {"finalized": bool(available_rows), "date": session_date, "row_count": len(available_rows)}
