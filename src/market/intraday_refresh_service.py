"""Scheduled and manual intraday proxy refresh pipeline."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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
from src.market.intraday_provider import bar_duration_minutes, fetch_daily_price_history, fetch_intraday_bars
from src.market.intraday_revaluation import revalue_mark_sensitive_outputs
from src.market.market_hours import (
    market_session_status,
    next_scheduled_refresh,
    should_run_scheduled_refresh,
)
from src.market.paper_portfolio_ledger import (
    applied_paper_rebalance_for_date,
    build_paper_portfolio_daily_row,
    build_paper_portfolio_gap_fill_rows,
    build_paper_strategy_daily_rows,
    missing_paper_portfolio_business_dates,
    paper_portfolio_snapshot_payload,
    rebase_paper_portfolio_daily_row,
    upsert_paper_portfolio_daily,
    upsert_paper_strategy_daily,
)
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
    committed = build_committed_shadow_refresh_artifact(_refresh_root_from_artifact_path(artifact_path))
    if committed.get("strategies"):
        return committed
    if artifact_path.exists():
        return json.loads(artifact_path.read_text(encoding="utf-8"))
    return committed


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


def _date_from_iso(value: str | None) -> str | None:
    return str(value)[:10] if value else None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _fetch_result_has_daily_price_history(fetch_result: dict[str, Any]) -> bool:
    rows = (
        fetch_result.get("daily_price_history")
        or fetch_result.get("price_history")
        or fetch_result.get("market_proxy_price_history")
        or []
    )
    return isinstance(rows, list) and bool(rows)


def _paper_gap_history_start_date(existing_rows: list[dict[str, Any]], first_missing_date: str) -> str:
    prior_dates = sorted(
        {
            str(row.get("date") or row.get("trading_date") or "")[:10]
            for row in existing_rows
            if str(row.get("date") or row.get("trading_date") or "")[:10] < first_missing_date
        }
    )
    if prior_dates:
        return prior_dates[-1]
    try:
        parsed = date.fromisoformat(first_missing_date[:10])
    except ValueError:
        return first_missing_date[:10]
    return (parsed - timedelta(days=7)).isoformat()


def _paper_gap_history_end_date(through_date: str) -> str:
    try:
        parsed = date.fromisoformat(through_date[:10])
    except ValueError:
        return through_date[:10]
    return (parsed + timedelta(days=1)).isoformat()


def _snapshot_session_date(snapshot: dict[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    shadow = snapshot.get("shadow_intraday") or {}
    return (
        snapshot.get("market_session_date")
        or shadow.get("session_date")
        or _date_from_iso(snapshot.get("latest_completed_bar_ts_et"))
        or _date_from_iso(snapshot.get("latest_observation_ts_et"))
    )


def _snapshot_latest_as_of(snapshot: dict[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    marks = snapshot.get("marks") or {}
    data_quality = marks.get("data_quality") or {}
    return (
        data_quality.get("latest_completed_bar_ts_et")
        or snapshot.get("latest_completed_bar_ts_et")
        or snapshot.get("latest_observation_ts_et")
    )


def _status_started_at(status: dict[str, Any]) -> datetime | None:
    return _parse_iso_timestamp(status.get("started_at"))


def _refresh_status_is_stale(
    status: dict[str, Any],
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 90,
) -> bool:
    if not status.get("in_progress"):
        return False
    started = _status_started_at(status)
    if started is None:
        return False
    current = now or datetime.now(timezone.utc)
    return current - started > timedelta(minutes=stale_after_minutes)


def _lock_file_is_stale(lock_path: Path, *, stale_after_seconds: int | None) -> bool:
    if stale_after_seconds is None or stale_after_seconds <= 0 or not lock_path.exists():
        return False
    try:
        modified = datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    return datetime.now(timezone.utc) - modified > timedelta(seconds=stale_after_seconds)


def _snapshot_is_current_for_session(
    snapshot: dict[str, Any] | None,
    session_date: str,
) -> bool:
    if not snapshot:
        return False
    latest_as_of = _snapshot_latest_as_of(snapshot)
    return _snapshot_session_date(snapshot) == session_date or _date_from_iso(latest_as_of) == session_date


def refresh_lifecycle_status(
    config: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    interval_minutes: int | None = None,
) -> dict[str, Any]:
    """Classify whether the delayed intraday pipeline is current, stale, pending, or needs refresh."""
    cfg = config or load_intraday_config()
    status = read_refresh_status(cfg)
    interval = resolve_refresh_interval_minutes(
        cfg,
        interval_minutes=interval_minutes,
        selected_interval_minutes=status.get("selected_interval_minutes"),
    )
    lock_stale_after_minutes = max(int(cfg.get("lock_stale_after_minutes") or 90), interval * 2)
    stale_running = _refresh_status_is_stale(
        status,
        now=now,
        stale_after_minutes=lock_stale_after_minutes,
    )
    session = market_session_status(
        now,
        timezone=cfg["timezone"],
        holidays=cfg.get("market_holidays") or [],
        interval_minutes=interval,
    )
    snapshot = read_latest_snapshot(cfg)
    latest_as_of = _snapshot_latest_as_of(snapshot)
    latest_ts = _parse_iso_timestamp(latest_as_of)
    current_day_snapshot = _snapshot_is_current_for_session(snapshot, session.session_date)
    last_error = status.get("last_error")
    state = "closed"
    reason = "market_closed"
    if status.get("in_progress") and not stale_running:
        state = "pending"
        reason = "refresh_in_progress"
    elif status.get("state") in {"failed", "cooldown"} and last_error and not current_day_snapshot:
        state = "provider_failed"
        reason = "provider_failed_no_current_snapshot"
    elif session.status == "Open":
        if not current_day_snapshot:
            state = "refresh_needed"
            reason = "missing_current_day_intraday_snapshot"
        elif latest_ts is None:
            state = "refresh_needed"
            reason = "missing_latest_market_observation"
        else:
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            age = (current.astimezone(latest_ts.tzinfo) - latest_ts).total_seconds() / 60
            stale_after = stale_after_minutes_for(cfg, interval)
            if age > stale_after:
                state = "stale"
                reason = "current_day_intraday_snapshot_stale"
            else:
                state = "current"
                reason = "current_day_intraday_snapshot_available"
    elif current_day_snapshot:
        state = "current"
        reason = "current_day_snapshot_available_outside_regular_session"
    elif status.get("state") in {"failed", "cooldown"} and last_error:
        state = "provider_failed"
        reason = "provider_failed_latest_available_preserved"
    elif session.is_trading_day and session.status in {"Pre-market", "After-hours"}:
        state = "closed"
        reason = f"market_{session.status.lower().replace('-', '_')}"
    if stale_running and state == "pending":
        state = "refresh_needed" if session.status == "Open" else "stale"
        reason = "stale_refresh_lock_or_status_recovered"
    return {
        "state": state,
        "reason": reason,
        "market_status": session.status,
        "market_session_date": session.session_date,
        "is_trading_day": session.is_trading_day,
        "refresh_needed": state == "refresh_needed",
        "pending": state == "pending",
        "provider_failed": state == "provider_failed",
        "latest_snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
        "latest_snapshot_session_date": _snapshot_session_date(snapshot),
        "latest_market_observation_at": latest_as_of,
        "last_successful_refresh_at": snapshot.get("refresh_completed_at") if snapshot else status.get("last_success_at"),
        "last_error": last_error,
        "status_state": status.get("state") or "idle",
        "status_in_progress": bool(status.get("in_progress") and not stale_running),
        "stale_status_recovered": stale_running,
        "refresh_interval_minutes": interval,
        "lock_stale_after_minutes": lock_stale_after_minutes,
    }


def _is_provider_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("429", "too many requests", "rate limit", "rate-limited", "cooldown"))


@contextmanager
def refresh_lock(lock_path: Path, *, stale_after_seconds: int | None = None):
    acquired = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if _lock_file_is_stale(lock_path, stale_after_seconds=stale_after_seconds):
            try:
                lock_path.unlink()
            except OSError:
                pass
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
    lifecycle = refresh_lifecycle_status(cfg, interval_minutes=interval)
    in_progress = bool(status.get("in_progress") and not lifecycle.get("stale_status_recovered"))
    state = status.get("state") or "idle"
    if in_progress:
        state = "refreshing"
    if lifecycle.get("state") == "pending":
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
        "refresh_lifecycle_state": lifecycle["state"],
        "refresh_needed": lifecycle["refresh_needed"],
        "refresh_lifecycle": lifecycle,
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
        "scheduler_deployment_note": (
            "In-process scheduler runs while the service is awake; first dashboard open can request a controlled refresh."
        ),
        "demo_hosting": demo,
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
    stale_after_seconds = max(int(cfg.get("lock_stale_after_minutes") or 90), interval * 2) * 60
    with refresh_lock(lock_path, stale_after_seconds=stale_after_seconds) as acquired:
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
            trading_date = (
                fetch_result.get("market_session_date")
                or fetch_result.get("session_date")
                or max((str(row.get("session_date") or "") for row in fetch_result.get("rows") or []), default="")
                or session.session_date
            )
            paper_rebalance = applied_paper_rebalance_for_date(refresh_root, trading_date)

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
                rebalance=paper_rebalance,
            )
            strategy_paper_rows = build_paper_strategy_daily_rows(
                artifact,
                fetch_result,
                refresh_status=refresh_coverage_status,
                position_source=position_source,
                rebalance=paper_rebalance,
            )
            paper_prices_stale = bool(fetch_result.get("stale_tickers"))
            if paper_prices_stale:
                refresh_warnings.append(
                    "paper daily ledger not updated because delayed quote freshness is stale; "
                    "latest good paper row is preserved"
                )
            if paper_row and not paper_prices_stale:
                existing_paper_rows = paper_portfolio_snapshot_payload(refresh_root, limit=10_000).get("rows") or []
                paper_gap_missing_dates = missing_paper_portfolio_business_dates(
                    existing_paper_rows,
                    through_date=str(paper_row.get("date") or ""),
                    holidays=cfg.get("market_holidays") or [],
                )
                if paper_gap_missing_dates and not _fetch_result_has_daily_price_history(fetch_result):
                    if fetch_fn is None:
                        try:
                            fetch_result["daily_price_history"] = fetch_daily_price_history(
                                tickers,
                                start_date=_paper_gap_history_start_date(existing_paper_rows, paper_gap_missing_dates[0]),
                                end_date=_paper_gap_history_end_date(str(paper_row.get("date") or "")),
                                timeout_seconds=int(cfg.get("request_timeout_seconds") or 20),
                                retry_attempts=int(cfg.get("retry_attempts") or 3),
                                backoff_seconds=list(cfg.get("backoff_seconds") or [5, 15, 30]),
                            )
                            fetch_result["daily_price_history_provider"] = "yfinance"
                        except Exception as exc:
                            refresh_warnings.append(
                                "paper daily gap fill pending; delayed daily close history unavailable "
                                f"for {', '.join(paper_gap_missing_dates)}: {exc}"
                            )
                    else:
                        refresh_warnings.append(
                            "paper daily gap fill pending; delayed daily close history unavailable "
                            f"for {', '.join(paper_gap_missing_dates)}"
                        )
                paper_gap_rows = build_paper_portfolio_gap_fill_rows(
                    artifact,
                    fetch_result,
                    existing_rows=existing_paper_rows,
                    through_date=str(paper_row.get("date") or ""),
                    holidays=cfg.get("market_holidays") or [],
                    position_source=position_source,
                    rebalance=paper_rebalance,
                )
                paper_gap_fill_dates = [row["date"] for row in paper_gap_rows]
                paper_gap_unfilled_dates = [
                    row_date for row_date in paper_gap_missing_dates
                    if row_date not in set(paper_gap_fill_dates)
                ]
                if paper_gap_unfilled_dates and _fetch_result_has_daily_price_history(fetch_result):
                    refresh_warnings.append(
                        "paper daily gap fill incomplete; paired delayed close history unavailable "
                        f"for {', '.join(paper_gap_unfilled_dates)}"
                    )
                prior_paper_rows = [
                    row for row in [*existing_paper_rows, *paper_gap_rows]
                    if str(row.get("date") or "") < str(paper_row.get("date") or "")
                ]
                prior_paper_nav = None
                if prior_paper_rows:
                    latest_prior = sorted(prior_paper_rows, key=lambda row: str(row.get("date") or ""))[-1]
                    prior_paper_nav = _to_float(latest_prior.get("ending_nav") or latest_prior.get("nav"))
                paper_row = rebase_paper_portfolio_daily_row(paper_row, prior_paper_nav)
                paper_payload = None
                for gap_row in paper_gap_rows:
                    paper_payload = upsert_paper_portfolio_daily(refresh_root, gap_row)
                paper_payload = upsert_paper_portfolio_daily(refresh_root, paper_row)
                strategy_payload = (
                    upsert_paper_strategy_daily(refresh_root, strategy_paper_rows)
                    if strategy_paper_rows else {"rows": []}
                )
                paper_update = {
                    "portfolio_row_updated": True,
                    "strategy_rows_updated": len(strategy_paper_rows),
                    "gap_rows_updated": len(paper_gap_rows),
                    "gap_fill_dates": paper_gap_fill_dates,
                    "gap_fill_missing_dates": paper_gap_missing_dates,
                    "gap_fill_unfilled_dates": paper_gap_unfilled_dates,
                    "trading_date": paper_row.get("date"),
                    "nav": paper_row.get("ending_nav"),
                    "daily_pnl": paper_row.get("daily_pnl"),
                    "daily_return": paper_row.get("daily_return"),
                    "refresh_status": refresh_coverage_status,
                    "row_count": len(paper_payload.get("rows") or []),
                    "strategy_row_count": len(strategy_payload.get("rows") or []),
                    "paper_transaction_cost": paper_row.get("paper_transaction_cost"),
                    "applied_paper_rebalance_plan_id": paper_rebalance.get("applied_plan_id"),
                    "paper_only": True,
                    "delayed_market_data": True,
                    "not_live_market_data": True,
                    "is_official_ledger": False,
                }
            else:
                paper_update = {
                    **no_paper_update,
                    "reason": (
                        "stale_delayed_quotes_preserved_paper_ledger"
                        if paper_prices_stale else "no_priced_committed_shadow_holdings"
                    ),
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
                "market_session_date": trading_date,
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
    if not has_snapshot:
        return "Refresh needed"
    if freshness == "Current":
        return "Current intraday proxy"
    if freshness == "Delayed":
        return "Delayed"
    if freshness == "Stale":
        return "Stale"
    return "Latest market close"
