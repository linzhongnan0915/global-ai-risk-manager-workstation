"""Minimal platform registry and SQLite daily shadow store for retained strategies."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import json
import sqlite3

import pandas as pd
import yaml

from src.market.market_hours import is_trading_day
from src.risk.performance import drawdown_series
from src.strategies.liquidity_resilience import SPEC as LIQUIDITY_SPEC
from src.strategies.realized_skewness import SPEC as SKEWNESS_SPEC
from src.strategies.strategy_factory import build_execution_returns, common_eligibility, load_context, rank_and_weight
from src.strategies.worldquant.data_loader import load_ohlcv_csv
from src.strategies.worldquant.market_data import download_ohlcv, validate_ohlcv_long_format
from src.strategies.worldquant.portfolio_returns import compute_portfolio_returns_from_weights

MEMBER_SPECS = (LIQUIDITY_SPEC, SKEWNESS_SPEC)
COMPOSITE_ID = "STRATEGY_21_RESEARCH_COMPOSITE_V1"
COMPOSITE_WEIGHTS = {"C2A2_020": 0.5, "C2B2_004": 0.5}
ALLOWED_FILTERS = {"RESEARCH_COMPOSITE_MEMBER", "RESEARCH_COMPOSITE", "RESEARCH_CANDIDATE", "ARCHIVE", "BLOCKED", "ALL"}
DEPLOYMENT_REGISTRY = Path("data/config/retained_strategy_registry.json")


def initialize_database(path: str | Path) -> sqlite3.Connection:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_strategy_returns (
          strategy_id TEXT, date TEXT, data_label TEXT, net_return REAL, PRIMARY KEY(strategy_id, date, data_label));
        CREATE TABLE IF NOT EXISTS daily_strategy_positions (
          strategy_id TEXT, date TEXT, ticker TEXT, data_label TEXT, target_weight REAL,
          PRIMARY KEY(strategy_id, date, ticker, data_label));
        CREATE TABLE IF NOT EXISTS daily_strategy_status (
          strategy_id TEXT, date TEXT, data_label TEXT, status TEXT, run_status TEXT, latest_market_date TEXT,
          PRIMARY KEY(strategy_id, date, data_label));
        CREATE TABLE IF NOT EXISTS daily_risk_alerts (
          strategy_id TEXT, date TEXT, data_label TEXT, alert_type TEXT, detail TEXT,
          PRIMARY KEY(strategy_id, date, data_label, alert_type));
        CREATE TABLE IF NOT EXISTS pipeline_runs (
          run_date TEXT, latest_market_date TEXT, data_label TEXT, run_status TEXT, detail TEXT,
          PRIMARY KEY(run_date, data_label));
        """
    )
    existing = {row[1] for row in connection.execute("PRAGMA table_info(pipeline_runs)")}
    for name, kind in (
        ("requested_market_date", "TEXT"), ("retrieved_market_date", "TEXT"), ("usable_market_date", "TEXT"),
        ("ticker_success_count", "INTEGER"), ("ticker_failure_count", "INTEGER"),
    ):
        if name not in existing:
            connection.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {name} {kind}")
    return connection


def _upsert(connection: sqlite3.Connection, table: str, columns: list[str], values: tuple) -> None:
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})", values
    )


def _historical_summary(factory_root: Path, strategy_id: str) -> dict:
    return json.loads((factory_root / strategy_id / "summary.json").read_text(encoding="utf-8"))


def strategy_21_allocation(strategy_id: str, status: str) -> float:
    return 0.0 if status in {"ARCHIVE", "BLOCKED"} else COMPOSITE_WEIGHTS.get(strategy_id, 0.0)


def platform_strategy_registry(factory_root: str | Path, composite_root: str | Path, status_filter: str = "ALL") -> list[dict]:
    normalized = status_filter.upper()
    if normalized not in ALLOWED_FILTERS:
        raise ValueError(f"unsupported strategy status filter: {status_filter}")
    if DEPLOYMENT_REGISTRY.exists():
        rows = json.loads(DEPLOYMENT_REGISTRY.read_text(encoding="utf-8"))["strategies"]
        for row in rows:
            if row["status"] in {"ARCHIVE", "BLOCKED"}:
                row["strategy_21_allocation"] = 0.0
        return rows if normalized == "ALL" else [row for row in rows if row["status"] == normalized]
    factory = Path(factory_root)
    composite = json.loads((Path(composite_root) / "strategy_21_summary.json").read_text(encoding="utf-8"))
    rows = []
    for spec in MEMBER_SPECS:
        summary = _historical_summary(factory, spec.strategy_id)
        rows.append(
            {
                "strategy_id": spec.strategy_id, "name": spec.name, "status": "RESEARCH_COMPOSITE_MEMBER",
                "allocation_eligible": False, "strategy_21_allocation": strategy_21_allocation(spec.strategy_id, "RESEARCH_COMPOSITE_MEMBER"),
                "net_return": summary["cumulative_net_return"], "sharpe": summary["net_sharpe"],
                "max_drawdown": summary["max_drawdown"], "turnover": summary["average_daily_turnover"],
                "ic": summary["mean_ic"], "decile_spread": summary["d10_minus_d1"],
                "status_reason": "Retained research-composite member; not allocation approved.",
                "latest_data_date": pd.read_csv(factory / spec.strategy_id / "daily_returns.csv")["date"].iloc[-1],
            }
        )
    rows.append(
        {
            "strategy_id": COMPOSITE_ID, "name": "Strategy 21 Research Composite v1",
            "status": "RESEARCH_COMPOSITE", "allocation_eligible": False, "strategy_21_allocation": 0.0,
            "net_return": composite["cumulative_return"], "sharpe": composite["sharpe"],
            "max_drawdown": composite["max_drawdown"], "turnover": None, "ic": None, "decile_spread": None,
            "status_reason": "Research-only composite; not live or allocation approved.",
            "latest_data_date": pd.read_csv(Path(composite_root) / "strategy_21_daily_returns.csv")["date"].iloc[-1],
        }
    )
    return rows if normalized == "ALL" else [row for row in rows if row["status"] == normalized]


def _fresh_enough(latest: pd.Timestamp, as_of: date, max_stale_days: int) -> bool:
    return (pd.Timestamp(as_of) - latest.normalize()).days <= max_stale_days


def latest_completed_trading_day(as_of: date, holidays: list[str]) -> date:
    probe = as_of - timedelta(days=1)
    while not is_trading_day(probe, holidays):
        probe -= timedelta(days=1)
    return probe


def update_shadow_ohlcv(
    ohlcv_path: str | Path, *, as_of: date, holidays_path: str | Path, min_success_ratio: float = 0.90,
) -> dict:
    path = Path(ohlcv_path)
    cached = load_ohlcv_csv(path)
    cached_latest = pd.to_datetime(cached["date"]).max().date()
    config = yaml.safe_load(Path(holidays_path).read_text(encoding="utf-8"))["intraday_refresh"]
    requested = latest_completed_trading_day(as_of, config.get("market_holidays", []))
    tickers = sorted(cached["ticker"].astype(str).unique())
    if cached_latest >= requested:
        return {
            "requested_market_date": requested.isoformat(), "retrieved_market_date": cached_latest.isoformat(),
            "usable_market_date": cached_latest.isoformat(), "ticker_success_count": len(tickers),
            "ticker_failure_count": 0, "updated": False,
        }
    incremental, _, _ = download_ohlcv(
        tickers, start_date=(cached_latest + timedelta(days=1)).isoformat(),
        end_date=(requested + timedelta(days=1)).isoformat(), include_rejected_history=True,
    )
    retrieved = pd.to_datetime(incremental["date"]).max().date() if not incremental.empty else None
    success = int(incremental.loc[incremental["date"] == requested.isoformat(), "ticker"].nunique())
    failure = len(tickers) - success
    usable = retrieved == requested and success / len(tickers) >= min_success_ratio
    if usable:
        merged = validate_ohlcv_long_format(
            pd.concat([cached, incremental], ignore_index=True).drop_duplicates(["ticker", "date"], keep="last")
        )
        temporary = path.with_suffix(".tmp.csv")
        merged.to_csv(temporary, index=False)
        temporary.replace(path)
    return {
        "requested_market_date": requested.isoformat(),
        "retrieved_market_date": retrieved.isoformat() if retrieved else None,
        "usable_market_date": requested.isoformat() if usable else cached_latest.isoformat(),
        "ticker_success_count": success, "ticker_failure_count": failure, "updated": usable,
    }


def run_daily_shadow(
    ohlcv_path: str | Path, database_path: str | Path, factory_root: str | Path,
    composite_root: str | Path, *, as_of: date | None = None, max_stale_days: int = 1,
    update_result: dict | None = None,
) -> dict:
    run_date = as_of or date.today()
    context = load_context(ohlcv_path)
    latest = pd.Timestamp(context.panels["close"].index.max())
    fresh = _fresh_enough(latest, run_date, max_stale_days)
    connection = initialize_database(database_path)
    statuses = []
    member_returns: dict[str, float] = {}
    try:
        for spec in MEMBER_SPECS:
            score = spec.signal_function(context)
            eligible = common_eligibility(score, context, spec)
            target, _ = rank_and_weight(score, eligible, spec)
            latest_weights = target.loc[latest]
            for ticker, weight in latest_weights[latest_weights != 0].items():
                _upsert(
                    connection, "daily_strategy_positions",
                    ["strategy_id", "date", "ticker", "data_label", "target_weight"],
                    (spec.strategy_id, latest.date().isoformat(), ticker, "SHADOW", float(weight)),
                )
            run_status = "OK" if fresh else "STALE_MARKET_DATA"
            _upsert(
                connection, "daily_strategy_status",
                ["strategy_id", "date", "data_label", "status", "run_status", "latest_market_date"],
                (spec.strategy_id, run_date.isoformat(), "SHADOW", "RESEARCH_COMPOSITE_MEMBER", run_status, latest.date().isoformat()),
            )
            if fresh:
                asset_returns, lag, definition = build_execution_returns(context, spec)
                result = compute_portfolio_returns_from_weights(
                    target, asset_returns, execution_lag=lag, buy_bps=spec.buy_bps,
                    sell_bps=spec.sell_bps, return_definition=definition,
                )
                member_returns[spec.strategy_id] = float(result.net_return.loc[latest])
                _upsert(
                    connection, "daily_strategy_returns",
                    ["strategy_id", "date", "data_label", "net_return"],
                    (spec.strategy_id, latest.date().isoformat(), "SHADOW", member_returns[spec.strategy_id]),
                )
            else:
                _upsert(
                    connection, "daily_risk_alerts",
                    ["strategy_id", "date", "data_label", "alert_type", "detail"],
                    (spec.strategy_id, run_date.isoformat(), "SHADOW", "STALE_MARKET_DATA", f"latest market date {latest.date()}"),
                )
            statuses.append(run_status)
        overall = "OK" if all(status == "OK" for status in statuses) else "STALE_MARKET_DATA"
        _upsert(
            connection, "daily_strategy_status",
            ["strategy_id", "date", "data_label", "status", "run_status", "latest_market_date"],
            (COMPOSITE_ID, run_date.isoformat(), "SHADOW", "RESEARCH_COMPOSITE", overall, latest.date().isoformat()),
        )
        if fresh:
            composite_return = sum(COMPOSITE_WEIGHTS[key] * member_returns[key] for key in COMPOSITE_WEIGHTS)
            _upsert(
                connection, "daily_strategy_returns",
                ["strategy_id", "date", "data_label", "net_return"],
                (COMPOSITE_ID, latest.date().isoformat(), "SHADOW", composite_return),
            )
        _write_standard_alerts(connection, factory_root, composite_root, run_date)
        update_values = update_result or {}
        _upsert(
            connection, "pipeline_runs",
            ["run_date", "latest_market_date", "data_label", "run_status", "detail", "requested_market_date",
             "retrieved_market_date", "usable_market_date", "ticker_success_count", "ticker_failure_count"],
            (run_date.isoformat(), latest.date().isoformat(), "SHADOW", overall, "idempotent daily shadow update",
             update_values.get("requested_market_date"), update_values.get("retrieved_market_date"),
             update_values.get("usable_market_date"), update_values.get("ticker_success_count"),
             update_values.get("ticker_failure_count")),
        )
        connection.commit()
        return {"run_status": overall, "latest_market_date": latest.date().isoformat(), "shadow_returns_written": fresh, **(update_result or {})}
    except Exception as exc:
        connection.rollback()
        _upsert(
            connection, "daily_risk_alerts",
            ["strategy_id", "date", "data_label", "alert_type", "detail"],
            (COMPOSITE_ID, run_date.isoformat(), "SHADOW", "FAILED_STRATEGY_RUN", str(exc)),
        )
        _upsert(
            connection, "pipeline_runs", ["run_date", "latest_market_date", "data_label", "run_status", "detail"],
            (run_date.isoformat(), latest.date().isoformat(), "SHADOW", "FAILED", str(exc)),
        )
        connection.commit()
        raise
    finally:
        connection.close()


def _write_standard_alerts(connection: sqlite3.Connection, factory_root: str | Path, composite_root: str | Path, run_date: date) -> None:
    composite = json.loads((Path(composite_root) / "strategy_21_summary.json").read_text(encoding="utf-8"))
    for strategy_id in (*COMPOSITE_WEIGHTS, COMPOSITE_ID):
        _upsert(
            connection, "daily_risk_alerts",
            ["strategy_id", "date", "data_label", "alert_type", "detail"],
            (strategy_id, run_date.isoformat(), "SHADOW", "STRATEGY_NOT_ALLOCATION_ELIGIBLE", "research-only strategy"),
        )
    for strategy_id in COMPOSITE_WEIGHTS:
        member = _historical_summary(Path(factory_root), strategy_id)
        if member["max_drawdown"] < -0.10:
            _upsert(connection, "daily_risk_alerts", ["strategy_id", "date", "data_label", "alert_type", "detail"],
                    (strategy_id, run_date.isoformat(), "SHADOW", "DRAWDOWN_ABOVE_10_PERCENT", str(member["max_drawdown"])))
    if composite["max_drawdown"] < -0.10:
        _upsert(connection, "daily_risk_alerts", ["strategy_id", "date", "data_label", "alert_type", "detail"],
                (COMPOSITE_ID, run_date.isoformat(), "SHADOW", "DRAWDOWN_ABOVE_10_PERCENT", str(composite["max_drawdown"])))
    if composite["alerts"]["component_over_50pct_total_pnl"]:
        _upsert(connection, "daily_risk_alerts", ["strategy_id", "date", "data_label", "alert_type", "detail"],
                (COMPOSITE_ID, run_date.isoformat(), "SHADOW", "CONTRIBUTION_ABOVE_50_PERCENT", ",".join(composite["alerts"]["component_over_50pct_total_pnl"])))
    pairwise = pd.read_csv(Path(composite_root) / "candidate_pairwise_analysis.csv")
    phase_members = set(COMPOSITE_WEIGHTS)
    high_correlation = pairwise.loc[
        pairwise["strategy_left"].isin(phase_members)
        & pairwise["strategy_right"].isin(phase_members)
        & (pairwise["daily_net_return_correlation"] > 0.70)
    ]
    for row in high_correlation.itertuples():
        _upsert(connection, "daily_risk_alerts", ["strategy_id", "date", "data_label", "alert_type", "detail"],
                (COMPOSITE_ID, run_date.isoformat(), "SHADOW", "PAIRWISE_CORRELATION_ABOVE_0_70", f"{row.strategy_left}/{row.strategy_right}:{row.daily_net_return_correlation:.3f}"))
