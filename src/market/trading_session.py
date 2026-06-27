"""Canonical trading-session state for operational dashboard contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from src.market.market_hours import is_trading_day


DEFAULT_TIMEZONE = "America/New_York"


@dataclass(frozen=True)
class TradingSessionState:
    calendar_date: str
    market_session_status: str
    is_trading_day: bool
    last_trading_session: str | None
    next_trading_session: str | None
    current_intraday_session: str | None
    latest_quote_asof: str | None
    quote_freshness: str
    daily_ledger_date: str | None
    daily_ledger_relation: str
    intraday_estimate_status: str
    session_warning: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "calendar_date": self.calendar_date,
            "market_session_status": self.market_session_status,
            "is_trading_day": self.is_trading_day,
            "last_trading_session": self.last_trading_session,
            "next_trading_session": self.next_trading_session,
            "current_intraday_session": self.current_intraday_session,
            "latest_quote_asof": self.latest_quote_asof,
            "quote_freshness": self.quote_freshness,
            "daily_ledger_date": self.daily_ledger_date,
            "daily_ledger_relation": self.daily_ledger_relation,
            "intraday_estimate_status": self.intraday_estimate_status,
            "session_warning": self.session_warning,
        }


def _local_datetime(value: datetime | date | str | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if value is None:
        return datetime.now(tz=tz)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
        return value.astimezone(tz)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=tz)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _date_from_asof(value: str | None, timezone: str) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return _local_datetime(text, timezone).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _previous_trading_day(day: date, holidays: Iterable[str]) -> str | None:
    probe = day - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(probe, holidays):
            return probe.isoformat()
        probe -= timedelta(days=1)
    return None


def _next_trading_day(day: date, holidays: Iterable[str]) -> str | None:
    probe = day + timedelta(days=1)
    for _ in range(14):
        if is_trading_day(probe, holidays):
            return probe.isoformat()
        probe += timedelta(days=1)
    return None


def build_trading_session_state(
    *,
    calendar_now: datetime | date | str | None = None,
    latest_quote_asof: str | None = None,
    daily_ledger_date: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    holidays: Iterable[str] | None = None,
    market_session_status_hint: str | None = None,
) -> dict[str, object]:
    """Build display/API session state without mutating accounting artifacts."""
    holidays = list(holidays or [])
    local = _local_datetime(calendar_now, timezone)
    day = local.date()
    calendar_date = day.isoformat()
    trading_day = is_trading_day(day, holidays)
    last_session = _previous_trading_day(day, holidays)
    next_session = _next_trading_day(day, holidays)
    current_session = calendar_date if trading_day else None
    quote_date = _date_from_asof(latest_quote_asof, timezone)

    if trading_day:
        market_session_status = market_session_status_hint or "TRADING_DAY"
    elif day.weekday() >= 5:
        market_session_status = "MARKET_CLOSED_WEEKEND"
    else:
        market_session_status = "NON_TRADING_DAY"

    if not quote_date:
        quote_freshness = "MISSING_QUOTE"
    elif current_session and quote_date == current_session:
        quote_freshness = "CURRENT_SESSION"
    else:
        quote_freshness = "STALE_PRIOR_SESSION"

    if not latest_quote_asof:
        daily_relation = "NO_QUOTE"
    elif daily_ledger_date and quote_date == str(daily_ledger_date)[:10]:
        daily_relation = "QUOTE_SESSION_ALREADY_RECORDED"
    else:
        daily_relation = "QUOTE_SESSION_NOT_RECORDED"

    if not trading_day:
        intraday_status = "NO_CURRENT_SESSION_INTRADAY"
    elif quote_freshness == "CURRENT_SESSION":
        intraday_status = "CURRENT_SESSION_INTRADAY"
    elif quote_freshness == "STALE_PRIOR_SESSION":
        intraday_status = "STALE_PRIOR_SESSION"
    else:
        intraday_status = "NO_CURRENT_SESSION_INTRADAY"

    warning = None
    if not trading_day:
        warning = "Calendar date is not a trading session; intraday estimate is not current-session live data."
    elif quote_freshness == "STALE_PRIOR_SESSION":
        warning = "Latest quote does not belong to the current trading session."
    elif daily_relation == "QUOTE_SESSION_ALREADY_RECORDED":
        warning = "Latest quote date is already represented in the daily ledger."

    return TradingSessionState(
        calendar_date=calendar_date,
        market_session_status=market_session_status,
        is_trading_day=trading_day,
        last_trading_session=last_session,
        next_trading_session=next_session,
        current_intraday_session=current_session,
        latest_quote_asof=latest_quote_asof,
        quote_freshness=quote_freshness,
        daily_ledger_date=daily_ledger_date,
        daily_ledger_relation=daily_relation,
        intraday_estimate_status=intraday_status,
        session_warning=warning,
    ).as_dict()
