"""U.S. regular-session calendar helpers for intraday proxy refresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketSessionInfo:
    status: str
    timezone: str
    session_date: str
    is_trading_day: bool
    next_refresh_at: str | None


def _to_local(now: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if now.tzinfo is None:
        return now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return now.astimezone(tz)


def is_market_holiday(day: date, holidays: Iterable[str]) -> bool:
    return day.isoformat() in set(holidays)


def is_trading_day(day: date, holidays: Iterable[str]) -> bool:
    return day.weekday() < 5 and not is_market_holiday(day, holidays)


def _session_status(local: datetime, holidays: Iterable[str], timezone: str) -> tuple[str, bool]:
    day = local.date()
    if not is_trading_day(day, holidays):
        return "Closed", False
    open_time = datetime.combine(day, time(9, 30), tzinfo=ZoneInfo(timezone))
    close_time = datetime.combine(day, time(16, 0), tzinfo=ZoneInfo(timezone))
    pre_open = datetime.combine(day, time(4, 0), tzinfo=ZoneInfo(timezone))
    after_close = datetime.combine(day, time(20, 0), tzinfo=ZoneInfo(timezone))
    if local < pre_open:
        return "Closed", True
    if local < open_time:
        return "Pre-market", True
    if local <= close_time:
        return "Open", True
    if local <= after_close:
        return "After-hours", True
    return "Closed", True


def market_session_status(
    now: datetime | None = None,
    *,
    timezone: str = "America/New_York",
    holidays: Iterable[str] | None = None,
    interval_minutes: int = 30,
) -> MarketSessionInfo:
    holidays = holidays or []
    local = _to_local(now or datetime.now(tz=ZoneInfo("UTC")), timezone)
    day = local.date()
    status, is_trading = _session_status(local, holidays, timezone)
    if not is_trading:
        return MarketSessionInfo(
            status="Closed",
            timezone=timezone,
            session_date=day.isoformat(),
            is_trading_day=False,
            next_refresh_at=_next_open_refresh(local, holidays, timezone).isoformat(),
        )
    return MarketSessionInfo(
        status=status,
        timezone=timezone,
        session_date=day.isoformat(),
        is_trading_day=True,
        next_refresh_at=_next_interval_refresh(local, interval_minutes, holidays, timezone).isoformat(),
    )


def should_run_scheduled_refresh(
    now: datetime | None,
    *,
    timezone: str,
    holidays: Iterable[str],
    regular_session_only: bool = True,
) -> bool:
    local = _to_local(now or datetime.now(tz=ZoneInfo("UTC")), timezone)
    status, is_trading = _session_status(local, holidays, timezone)
    if not is_trading:
        return False
    if regular_session_only:
        return status == "Open"
    return status in {"Open", "Pre-market", "After-hours"}


def _next_open_refresh(local: datetime, holidays: Iterable[str], timezone: str) -> datetime:
    probe = local
    for _ in range(10):
        if is_trading_day(probe.date(), holidays):
            open_time = datetime.combine(probe.date(), time(9, 30), tzinfo=ZoneInfo(timezone))
            if probe <= open_time:
                return open_time
        probe = datetime.combine(probe.date() + timedelta(days=1), time(9, 30), tzinfo=ZoneInfo(timezone))
    return local + timedelta(hours=12)


def _next_interval_refresh(local: datetime, interval_minutes: int, holidays: Iterable[str], timezone: str) -> datetime:
    status, is_trading = _session_status(local, holidays, timezone)
    if not is_trading:
        return _next_open_refresh(local, holidays, timezone)
    if status != "Open":
        open_time = datetime.combine(local.date(), time(9, 30), tzinfo=ZoneInfo(timezone))
        if status == "Pre-market" and local < open_time:
            return open_time
        return _next_open_refresh(local + timedelta(days=1), holidays, timezone)
    minute = ((local.minute // interval_minutes) + 1) * interval_minutes
    hour = local.hour
    if minute >= 60:
        hour += 1
        minute = 0
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    close_time = datetime.combine(local.date(), time(16, 0), tzinfo=ZoneInfo(timezone))
    if candidate > close_time:
        return _next_open_refresh(local + timedelta(days=1), holidays, timezone)
    return candidate


def next_scheduled_refresh(
    now: datetime | None,
    interval_minutes: int,
    *,
    timezone: str,
    holidays: Iterable[str],
) -> datetime:
    local = _to_local(now or datetime.now(tz=ZoneInfo("UTC")), timezone)
    return _next_interval_refresh(local, interval_minutes, holidays, timezone)
