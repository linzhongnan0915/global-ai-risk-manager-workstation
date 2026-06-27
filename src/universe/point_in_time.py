"""Point-in-time membership helpers for universe consumers."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

POINT_IN_TIME_STATUS = "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"


def get_universe_members(
    universe_name: str,
    as_of_date: str | date | datetime,
    *,
    membership_path: str | Path = "data/universe/universe_membership.csv",
) -> dict[str, Any]:
    path = Path(membership_path)
    if not path.exists():
        return {
            "universe_name": universe_name,
            "as_of_date": _date_string(as_of_date),
            "members": [],
            "member_count": 0,
            "point_in_time_status": POINT_IN_TIME_STATUS,
            "warnings": ["Universe membership artifact is unavailable."],
        }
    frame = pd.read_csv(path)
    members = filter_point_in_time_members(frame, universe_name, as_of_date)
    return {
        "universe_name": universe_name,
        "as_of_date": _date_string(as_of_date),
        "members": members["ticker"].astype(str).sort_values().tolist(),
        "member_count": int(len(members)),
        "point_in_time_status": POINT_IN_TIME_STATUS,
        "version": _safe_first(members, "version"),
        "source": _safe_first(members, "source"),
        "warnings": ["Current membership only - not survivor-bias-free."],
    }


def filter_point_in_time_members(
    membership: pd.DataFrame,
    universe_name: str,
    as_of_date: str | date | datetime,
) -> pd.DataFrame:
    required = {"universe_name", "ticker", "membership_start_date", "membership_end_date"}
    missing = required - set(membership.columns)
    if missing:
        raise ValueError(f"membership data missing required columns: {sorted(missing)}")
    signal_date = pd.Timestamp(as_of_date)
    working = membership.loc[membership["universe_name"] == universe_name].copy()
    if working.empty:
        return working
    start = pd.to_datetime(working["membership_start_date"], errors="coerce")
    end = pd.to_datetime(working["membership_end_date"], errors="coerce")
    active = start.le(signal_date) & (end.isna() | end.gt(signal_date))
    return working.loc[active].copy()


def _date_string(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _safe_first(frame: pd.DataFrame, column: str) -> Any:
    if frame.empty or column not in frame:
        return None
    return frame[column].dropna().astype(str).iloc[0] if not frame[column].dropna().empty else None
