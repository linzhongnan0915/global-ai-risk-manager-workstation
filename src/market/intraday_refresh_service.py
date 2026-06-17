"""Scheduled and manual intraday proxy refresh pipeline."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.market.demo_hosting import demo_scheduler_label, intraday_scheduler_enabled, is_demo_hosting
from src.market.refresh_auth import refresh_api_token_configured
from src.market.intraday_config import (
    bar_interval_for_refresh,
    load_intraday_config,
    resolve_refresh_interval_minutes,
    stale_after_minutes_for,
)
from src.market.intraday_provider import bar_duration_minutes, fetch_intraday_bars
from src.market.intraday_revaluation import revalue_mark_sensitive_outputs
from src.market.market_hours import (
    market_session_status,
    next_scheduled_refresh,
    should_run_scheduled_refresh,
)
from src.market.paper_portfolio_ledger import build_paper_portfolio_daily_row, upsert_paper_portfolio_daily
from src.market.snapshot_store import (
    new_snapshot_id,
    publish_snapshot,
    read_latest_pointer,
    read_latest_snapshot,
    read_refresh_status,
    write_refresh_status,
)
from src.market.yfinance_client import load_market_universe
from src.strategies.shadow_intraday import (
    build_shadow_intraday_estimates,
    collect_shadow_position_tickers,
    daily_shadow_return_exists,
    finalize_daily_shadow_returns,
)

DEFAULT_ARTIFACT_PATH = Path("output/dashboard_artifact.json")
BACKGROUND_SCHEDULER_ENABLED: bool | None = None


def set_background_scheduler_enabled(enabled: bool | None) -> None:
    global BACKGROUND_SCHEDULER_ENABLED
    BACKGROUND_SCHEDULER_ENABLED = enabled


def load_dashboard_artifact(path: Path | str = DEFAULT_ARTIFACT_PATH) -> dict[str, Any]:
    artifact_path = Path(path)
    if artifact_path.exists():
        return json.loads(artifact_path.read_text(encoding="utf-8"))
    return build_committed_shadow_refresh_artifact(_refresh_root_from_artifact_path(artifact_path))


def _refresh_root_from_artifact_path(path: Path | str) -> Path:
    resolved = Path(path).resolve()
    return resolved.parent.parent if resolved.parent.name == "output" else resolved.parent


def load_committed_operational_canonical(root: Path) -> dict[str, Any]:
    path = root / "dashboard" / "data" / "canonical_operational.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_committed_shadow_refresh_artifact(root: Path) -> dict[str, Any]:
    """Build an in-memory Refresh Scheme B baseline without restoring legacy artifacts."""
    payload = load_committed_operational_canonical(root)
    portfolio = payload.get("portfolio_summary") or {}
    strategies = payload.get("strategies") or []
    holdings = payload.get("holdings") or []
    latest_date = max((row.get("date") or "" for row in holdings), default="")
    holdings_by_strategy: dict[str, list[dict[str, Any]]] = {}
    for row in holdings:
        if row.get("date") != latest_date or not row.get("ticker"):
            continue
        if float(row.get("target_weight") or 0) == 0:
            continue
        strategy_id = str(row.get("strategy_id") or row.get("internal_id") or "")
        if not strategy_id:
            continue
        holdings_by_strategy.setdefault(strategy_id, []).append(
            {
                "ticker": str(row["ticker"]),
                "source_ticker": str(row["ticker"]),
                "weight": float(row.get("target_weight") or 0),
            }
        )

    artifact_strategies: list[dict[str, Any]] = []
    current_weights: dict[str, float] = {}
    for strategy in strategies:
        strategy_id = str(strategy.get("internal_id") or strategy.get("strategy_id") or "")
        if not strategy_id:
            continue
        weight = float(strategy.get("current_weight") or strategy.get("weight") or 0)
        if strategy.get("membership_state") == "executed" or strategy_id in holdings_by_strategy:
            current_weights[strategy_id] = weight
        artifact_strategies.append(
            {
                "strategy_id": strategy_id,
                "name": strategy.get("display_name") or strategy.get("name") or strategy_id,
                "current_weight": weight,
                "position_packet": {"latest_positions": holdings_by_strategy.get(strategy_id, [])},
            }
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    initial_capital = portfolio.get("initial_shadow_capital") or portfolio.get("nav") or 1_000_000
    return {
        "as_of_date": portfolio.get("as_of_date") or portfolio.get("official_ledger_date") or latest_date,
        "initial_capital": float(initial_capital),
        "allocation": {
            "current_weights": current_weights,
            "approval_required": True,
            "rationale": "Refresh Scheme B: committed shadow holdings; no live brokerage positions or fills.",
        },
        "strategies": artifact_strategies,
        "factors": {"portfolio_factor_exposure_current": {}},
        "risk_limits": {"checks": [], "factors": {"checks": []}},
        "operating_period_risk": {"pnl": {"cumulative_return": {"available": False, "value": None}}},
        "data_classification": {
            "is_live_portfolio_data": False,
            "brokerage_execution_enabled": False,
            "market_data_mode": "delayed_yfinance_proxy",
            "paper_only": True,
        },
        "build_metadata": {
            "artifact_generated_at": generated_at,
            "source": "committed_shadow_holdings",
            "legacy_artifact_position_estimate_authoritative": False,
        },
        "refresh_scheme": "B",
        "position_source": "committed_shadow_holdings",
        "legacy_artifact_position_estimate_authoritative": False,
    }


def collect_refresh_tickers(artifact: dict[str, Any]) -> list[str]:
    tickers = {row["ticker"] for row in load_market_universe()}
    for strategy in artifact.get("strategies") or []:
        for position in strategy.get("position_packet", {}).get("latest_positions") or []:
            ticker = position.get("source_ticker") or position.get("ticker")
            if ticker:
                tickers.add(str(ticker))
    return sorted(tickers)


def collect_committed_shadow_holding_tickers(root: Path) -> list[str]:
    """Use committed operational holdings as a non-live, auditable refresh universe."""
    payload = load_committed_operational_canonical(root)
    holdings = payload.get("holdings") or []
    latest_date = max((row.get("date") or "" for row in holdings), default="")
    tickers = {
        str(row.get("ticker"))
        for row in holdings
        if row.get("date") == latest_date and row.get("ticker") and float(row.get("target_weight") or 0) != 0
    }
    return sorted(tickers)


def _is_provider_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("429", "too many requests", "rate limit", "rate-limited", "cooldown"))


@contextmanager
def refresh_lock(lock_path: Path):
    acquired = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        acquired = True
        yield True
    except FileExistsError:
        yield False
    finally:
        if acquired and lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass


def build_refresh_status_payload(
    config: dict[str, Any] | None = None,
    *,
    interval_minutes: int | None = None,
) -> dict[str, Any]:
    cfg = config or load_intraday_config()
    status = read_refresh_status(cfg)
    interval = resolve_refresh_interval_minutes(
        cfg,
        interval_minutes=interval_minutes,
        selected_interval_minutes=status.get("selected_interval_minutes"),
    )
    session = market_session_status(
        timezone=cfg["timezone"],
        holidays=cfg.get("market_holidays") or [],
        interval_minutes=interval,
    )
    next_at = next_scheduled_refresh(
        None,
        interval,
        timezone=cfg["timezone"],
        holidays=cfg.get("market_holidays") or [],
    )
    status = read_refresh_status(cfg)
    pointer = read_latest_pointer(cfg)
    snapshot = read_latest_snapshot(cfg)
    latest_observation = None
    latest_completed_bar = None
    last_success = None
    snapshot_id = pointer.get("snapshot_id") if pointer else None
    if snapshot:
        latest_observation = snapshot.get("latest_observation_ts_et")
        latest_completed_bar = (
            (snapshot.get("marks") or {}).get("data_quality", {}).get("latest_completed_bar_ts_et")
            or snapshot.get("latest_completed_bar_ts_et")
            or latest_observation
        )
        last_success = snapshot.get("refresh_completed_at")
        freshness = (snapshot.get("marks") or {}).get("data_quality", {}).get("freshness")
    else:
        freshness = None
        last_success = status.get("last_success_at")
    in_progress = bool(status.get("in_progress"))
    state = status.get("state") or "idle"
    if in_progress:
        state = "refreshing"
    canonical_data_state = _canonical_data_state_label(
        session.status,
        freshness,
        has_snapshot=bool(snapshot),
        in_progress=in_progress,
        refresh_state=state,
        last_error=status.get("last_error"),
    )
    demo = is_demo_hosting()
    external_scheduler = refresh_api_token_configured()
    configured_scheduler_enabled = intraday_scheduler_enabled(
        config_enabled=bool(cfg.get("enabled", True)),
        force_start=None,
        force_disable=False,
    )
    scheduler_enabled = (
        BACKGROUND_SCHEDULER_ENABLED
        if BACKGROUND_SCHEDULER_ENABLED is not None
        else configured_scheduler_enabled
    )
    demo_label = demo_scheduler_label(scheduler_enabled)
    if external_scheduler:
        scheduler_label = "External active"
        scheduler_display = "External active"
    else:
        scheduler_label = demo_label
        scheduler_display = demo_label or ("Scheduler active" if scheduler_enabled else "idle")
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled", True)),
        "market_status": session.status,
        "market_session_date": session.session_date,
        "is_trading_day": session.is_trading_day,
        "timezone": cfg["timezone"],
        "refresh_cadence_minutes": interval,
        "selected_cadence_minutes": interval,
        "bar_interval": bar_interval_for_refresh(cfg, interval),
        "next_scheduled_refresh_at": next_at.isoformat(),
        "last_successful_refresh_at": last_success,
        "latest_market_observation_at": latest_observation,
        "latest_completed_market_bar_at": latest_completed_bar,
        "data_freshness": freshness if snapshot else status.get("data_freshness"),
        "scheduler_state": "external_active" if external_scheduler else state,
        "scheduler_enabled": scheduler_enabled or external_scheduler,
        "external_scheduler_active": external_scheduler,
        "scheduler_label": scheduler_label,
        "scheduler_display": scheduler_display,
        "canonical_data_state": canonical_data_state,
        "snapshot_id": snapshot_id,
        "previous_valid_snapshot_id": snapshot.get("previous_valid_snapshot_id") if snapshot else None,
        "refresh_state": state,
        "in_progress": in_progress,
        "last_error": status.get("last_error"),
        "ticker_count_requested": snapshot.get("ticker_count_requested") if snapshot else None,
        "ticker_count_successful": snapshot.get("ticker_count_successful") if snapshot else None,
        "failed_ticker_count": len(snapshot.get("missing_tickers") or []) if snapshot else None,
        "missing_tickers": snapshot.get("missing_tickers") if snapshot else [],
        "shadow_intraday": snapshot.get("shadow_intraday") if snapshot else None,
        "intraday_data_label": snapshot.get("intraday_data_label") if snapshot else None,
        "retry_count": status.get("retry_count"),
        "provider": cfg.get("provider", "yfinance"),
        "disclosure": (
            "Research market proxy refresh; not live portfolio or exchange data. "
            "Shared demo hosts may rate-limit yfinance; baseline artifact remains available."
            if demo
            else "Research market proxy refresh; not live portfolio or exchange data."
        ),
        "scheduler_deployment_note": "Render requires ENABLE_INTRADAY_SCHEDULER=1.",
        "demo_hosting": demo,
        "scheduler_label": scheduler_label,
    }


def set_refresh_cadence(
    interval_minutes: int,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist refresh cadence without triggering a market-data fetch."""
    cfg = config or load_intraday_config()
    interval = resolve_refresh_interval_minutes(cfg, interval_minutes=interval_minutes)
    status = read_refresh_status(cfg)
    status["selected_interval_minutes"] = interval
    write_refresh_status(status, cfg)
    return build_refresh_status_payload(cfg, interval_minutes=interval)


def run_intraday_refresh(
    *,
    interval_minutes: int | None = None,
    force: bool = False,
    artifact_path: Path | str = DEFAULT_ARTIFACT_PATH,
    config: dict[str, Any] | None = None,
    fetch_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute intraday proxy refresh. Manual and scheduled jobs share this path."""
    cfg = config or load_intraday_config()
    no_paper_update = {
        "portfolio_row_updated": False,
        "strategy_rows_updated": 0,
        "reason": "not_attempted",
    }
    status = read_refresh_status(cfg)
    interval = resolve_refresh_interval_minutes(
        cfg,
        interval_minutes=interval_minutes,
        selected_interval_minutes=status.get("selected_interval_minutes"),
    )

    session = market_session_status(
        timezone=cfg["timezone"],
        holidays=cfg.get("market_holidays") or [],
        interval_minutes=interval,
    )
    shadow_database = Path(cfg.get("shadow_database_path") or "output/shadow/strategy_shadow.db")
    needs_close_finalization = (
        session.status == "After-hours"
        and not daily_shadow_return_exists(shadow_database, session.session_date)
    )
    if not force and not should_run_scheduled_refresh(
        None,
        timezone=cfg["timezone"],
        holidays=cfg.get("market_holidays") or [],
        regular_session_only=bool(cfg.get("regular_session_only", True)),
    ) and not needs_close_finalization:
        payload = build_refresh_status_payload(cfg, interval_minutes=interval)
        payload.update(
            {
                "ok": True,
                "skipped": True,
                "reason": f"market_{session.status.lower().replace('-', '_')}",
                "message": "Scheduled intraday refresh skipped outside regular session.",
                "paper_performance_update": {**no_paper_update, "reason": "refresh_skipped"},
            }
        )
        return payload

    lock_path = Path(cfg["lock_path"])
    with refresh_lock(lock_path) as acquired:
        if not acquired:
            current = read_refresh_status(cfg)
            return {
                "ok": False,
                "error": "refresh_already_in_progress",
                "refresh_state": "refreshing",
                "in_progress": True,
                "snapshot_id": read_latest_pointer(cfg).get("snapshot_id") if read_latest_pointer(cfg) else None,
                "started_at": current.get("started_at"),
                "paper_performance_update": {**no_paper_update, "reason": "refresh_already_in_progress"},
            }

        started = datetime.now(timezone.utc)
        previous_pointer = read_latest_pointer(cfg)
        previous_snapshot_id = previous_pointer.get("snapshot_id") if previous_pointer else None
        write_refresh_status(
            {
                "state": "running",
                "in_progress": True,
                "started_at": started.isoformat(),
                "interval_minutes": interval,
                "selected_interval_minutes": interval,
                "trigger": "manual" if force else "scheduled",
                "last_error": None,
            },
            cfg,
        )

        try:
            refresh_root = _refresh_root_from_artifact_path(artifact_path)
            artifact = load_dashboard_artifact(artifact_path)
            baseline_allocation = dict(artifact.get("allocation", {}).get("current_weights") or {})
            baseline_signals_as_of = artifact.get("as_of_date")
            tickers = collect_committed_shadow_holding_tickers(refresh_root)
            position_source = "committed_shadow_holdings" if tickers else "missing"
            if not tickers:
                tickers = collect_shadow_position_tickers(shadow_database)
                position_source = "shadow_database" if tickers else "missing"
            if not tickers:
                raise ValueError("no committed SHADOW holdings available for Refresh Scheme B")
            bar_interval = bar_interval_for_refresh(cfg, interval)
            fetcher = fetch_fn or fetch_intraday_bars
            fetch_result = fetcher(
                tickers,
                bar_interval=bar_interval,
                timeout_seconds=int(cfg.get("request_timeout_seconds") or 20),
                retry_attempts=int(cfg.get("retry_attempts") or 3),
                backoff_seconds=list(cfg.get("backoff_seconds") or [5, 15, 30]),
                target_timezone=str(cfg.get("timezone") or "America/New_York"),
                stale_after_minutes=stale_after_minutes_for(cfg, interval),
                refresh_interval_minutes=interval,
            )
            latest_retrieved = fetch_result.get("latest_completed_bar_ts_et") or fetch_result.get("latest_observation_ts_et")
            previous_snapshot = read_latest_snapshot(cfg)
            previous_latest = (
                previous_snapshot.get("latest_completed_bar_ts_et") or previous_snapshot.get("latest_observation_ts_et")
                if previous_snapshot else None
            )
            if latest_retrieved and previous_latest and latest_retrieved < previous_latest:
                write_refresh_status(
                    {
                        "state": "idle", "in_progress": False, "last_success_at": previous_snapshot.get("refresh_completed_at"),
                        "last_snapshot_id": previous_snapshot.get("snapshot_id"), "selected_interval_minutes": interval,
                        "data_freshness": (previous_snapshot.get("marks") or {}).get("data_quality", {}).get("freshness"),
                        "last_error": None,
                    },
                    cfg,
                )
                payload = build_refresh_status_payload(cfg, interval_minutes=interval)
                payload.update({
                    "ok": True,
                    "skipped": True,
                    "reason": "stale_response_preserved_newer_snapshot",
                    "paper_performance_update": {**no_paper_update, "reason": "stale_response_preserved_newer_snapshot"},
                })
                return payload

            requested = int(fetch_result.get("ticker_count_requested") or len(tickers))
            successful = int(fetch_result.get("ticker_count_successful") or 0)
            ratio = successful / max(requested, 1)
            min_ratio = float(cfg.get("min_success_ticker_ratio") or 0.6)
            refresh_warnings: list[str] = []
            if successful <= 0:
                raise ValueError("no ticker coverage from delayed market-data provider")
            if ratio < min_ratio:
                refresh_warnings.append(
                    f"partial ticker coverage ({successful}/{requested}, below {min_ratio:.0%}); stale/missing ticker labels preserved"
                )
            refresh_coverage_status = "partial" if refresh_warnings or fetch_result.get("missing_tickers") or fetch_result.get("stale_tickers") else "fresh"

            marks = revalue_mark_sensitive_outputs(artifact, fetch_result, load_market_universe())
            shadow_intraday = build_shadow_intraday_estimates(
                shadow_database,
                fetch_result.get("rows") or [],
                notional=float(artifact.get("initial_capital") or 1_000_000),
            )
            marks["shadow_intraday"] = shadow_intraday
            marks["estimated_intraday_return"] = shadow_intraday.get("estimated_return")
            marks["estimated_intraday_pnl"] = shadow_intraday.get("estimated_pnl")
            marks["estimated_model_nav"] = (
                marks["baseline_model_nav"] * (1.0 + shadow_intraday["estimated_return"])
                if shadow_intraday.get("available") else None
            )
            marks["canonical_return_definition"] = "session first usable open to latest completed 5-minute close"
            marks["legacy_artifact_position_estimate_authoritative"] = False
            marks["position_source"] = position_source
            marks["position_source_disclosure"] = (
                "Committed operational shadow holdings are used only as the delayed yfinance pricing universe; "
                "no live brokerage positions or fills are represented."
                if position_source == "committed_shadow_holdings"
                else position_source
            )
            marks["strategy_marks"] = shadow_intraday.get("strategies") or []
            marks["refresh_warnings"] = refresh_warnings
            marks["paper_only"] = True
            marks["live_brokerage_execution"] = False
            marks["delayed_market_data"] = True
            marks["not_live_market_data"] = True
            paper_row = build_paper_portfolio_daily_row(
                artifact,
                fetch_result,
                refresh_status=refresh_coverage_status,
                warnings=refresh_warnings,
                position_source=position_source,
            )
            if paper_row:
                paper_payload = upsert_paper_portfolio_daily(refresh_root, paper_row)
                paper_update = {
                    "portfolio_row_updated": True,
                    "strategy_rows_updated": 0,
                    "trading_date": paper_row.get("date"),
                    "nav": paper_row.get("ending_nav"),
                    "daily_pnl": paper_row.get("daily_pnl"),
                    "daily_return": paper_row.get("daily_return"),
                    "refresh_status": refresh_coverage_status,
                    "row_count": len(paper_payload.get("rows") or []),
                    "paper_only": True,
                    "delayed_market_data": True,
                    "not_live_market_data": True,
                    "is_official_ledger": False,
                }
            else:
                paper_update = {
                    **no_paper_update,
                    "reason": "no_priced_committed_shadow_holdings",
                    "refresh_status": refresh_coverage_status,
                }
            daily_finalization = finalize_daily_shadow_returns(
                shadow_database,
                shadow_intraday,
                latest_completed_bar_ts=fetch_result.get("latest_completed_bar_ts_et"),
                bar_minutes=bar_duration_minutes(bar_interval),
            )
            completed = datetime.now(timezone.utc)
            snapshot_id = new_snapshot_id(completed)
            snapshot = {
                "snapshot_id": snapshot_id,
                "previous_valid_snapshot_id": previous_snapshot_id,
                "refresh_status": "success",
                "provider": fetch_result.get("provider") or cfg.get("provider"),
                "requested_bar_interval": bar_interval,
                "refresh_started_at": started.isoformat(),
                "refresh_completed_at": completed.isoformat(),
                "latest_observation_ts_et": fetch_result.get("latest_observation_ts_et"),
                "latest_completed_bar_ts_et": fetch_result.get("latest_completed_bar_ts_et"),
                "incomplete_current_bars": fetch_result.get("incomplete_current_bars") or [],
                "market_session_date": session.session_date,
                "market_session_status": session.status,
                "ticker_count_requested": requested,
                "ticker_count_successful": successful,
                "position_source": position_source,
                "missing_tickers": fetch_result.get("missing_tickers") or [],
                "stale_tickers": fetch_result.get("stale_tickers") or [],
                "warnings": refresh_warnings,
                "retry_count": int(fetch_result.get("retry_count") or 0),
                "refresh_interval_minutes": interval,
                "marks": marks,
                "intraday_data_label": "INTRADAY_SHADOW_ESTIMATE",
                "shadow_intraday": shadow_intraday,
                "latest_usable_prices": shadow_intraday.get("latest_usable_prices") or {},
                "daily_finalization": daily_finalization,
                "paper_performance_update": paper_update,
                "governance_preserved": {
                    "allocation_weights_unchanged": baseline_allocation,
                    "signals_as_of_unchanged": baseline_signals_as_of,
                    "execution_authorized": False,
                },
            }
            publish_snapshot(snapshot, cfg)
            write_refresh_status(
                {
                    "state": "idle",
                    "in_progress": False,
                    "last_success_at": completed.isoformat(),
                    "last_snapshot_id": snapshot_id,
                    "selected_interval_minutes": interval,
                    "data_freshness": marks.get("data_quality", {}).get("freshness"),
                    "last_error": None,
                    "retry_count": snapshot["retry_count"],
                },
                cfg,
            )
            result = build_refresh_status_payload(cfg, interval_minutes=interval)
            result.update(
                {
                    "ok": True,
                    "snapshot_id": snapshot_id,
                    "previous_valid_snapshot_id": previous_snapshot_id,
                    "refresh_status": "success",
                    "position_source": position_source,
                    "legacy_artifact_position_estimate_authoritative": False,
                    "position_source_disclosure": marks["position_source_disclosure"],
                    "warnings": refresh_warnings,
                    "paper_only": True,
                    "live_brokerage_execution": False,
                    "delayed_market_data": True,
                    "not_live_market_data": True,
                    "latest_market_observation_at": snapshot["latest_observation_ts_et"],
                    "last_successful_refresh_at": completed.isoformat(),
                    "paper_performance_update": paper_update,
                }
            )
            return result
        except Exception as exc:
            failed_at = datetime.now(timezone.utc)
            last_valid = read_latest_snapshot(cfg)
            if last_valid and _is_provider_rate_limit_error(exc):
                write_refresh_status(
                    {
                        "state": "cooldown",
                        "in_progress": False,
                        "last_error": str(exc),
                        "failed_at": failed_at.isoformat(),
                        "data_freshness": "Stale",
                        "last_snapshot_id": last_valid.get("snapshot_id"),
                        "selected_interval_minutes": interval,
                    },
                    cfg,
                )
                payload = build_refresh_status_payload(cfg, interval_minutes=interval)
                payload.update(
                    {
                        "ok": True,
                        "skipped": True,
                        "reason": "provider_rate_limited_stale_snapshot_preserved",
                        "refresh_status": "stale_cooldown",
                        "provider_cooldown": True,
                        "error": str(exc),
                        "snapshot_id": last_valid.get("snapshot_id"),
                        "previous_valid_snapshot_id": last_valid.get("previous_valid_snapshot_id"),
                        "data_freshness": "Stale",
                        "stale_usable": True,
                        "warnings": ["Delayed market-data provider rate-limited; previous valid snapshot preserved."],
                        "paper_performance_update": {**no_paper_update, "reason": "provider_rate_limited_stale_snapshot_preserved"},
                    }
                )
                return payload
            write_refresh_status(
                {
                    "state": "failed",
                    "in_progress": False,
                    "last_error": str(exc),
                    "failed_at": failed_at.isoformat(),
                    "data_freshness": "Failed" if not last_valid else "Stale",
                    "last_snapshot_id": last_valid.get("snapshot_id") if last_valid else None,
                },
                cfg,
            )
            payload = build_refresh_status_payload(cfg, interval_minutes=interval)
            payload.update(
                {
                    "ok": False,
                    "error": str(exc),
                    "refresh_status": "failed",
                    "snapshot_id": last_valid.get("snapshot_id") if last_valid else None,
                    "previous_valid_snapshot_id": last_valid.get("previous_valid_snapshot_id") if last_valid else None,
                    "data_freshness": "Failed" if not last_valid else "Stale",
                    "paper_performance_update": {**no_paper_update, "reason": "refresh_failed"},
                }
            )
            return payload


def read_latest_snapshot_payload(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_intraday_config()
    snapshot = read_latest_snapshot(cfg)
    if not snapshot:
        return {"ok": False, "error": "no_valid_snapshot"}
    return {"ok": True, **snapshot}


def _canonical_data_state_label(
    market_status: str,
    freshness: str | None,
    *,
    has_snapshot: bool,
    in_progress: bool,
    refresh_state: str,
    last_error: str | None,
) -> str:
    if in_progress:
        return "Refreshing"
    if refresh_state == "failed" or freshness == "Failed":
        return "Refresh failed"
    if market_status != "Open":
        return "Latest market close"
    if freshness == "Current":
        return "Current intraday proxy"
    if freshness == "Delayed":
        return "Delayed"
    if freshness == "Stale":
        return "Stale"
    if not has_snapshot:
        return "Latest market close"
    return "Latest market close"
