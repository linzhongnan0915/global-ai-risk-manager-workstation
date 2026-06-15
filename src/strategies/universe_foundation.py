"""Versioned point-in-time research universe foundation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

UNIVERSE_VERSION = "v1"
FORMAL_MEMBERSHIP_COLUMNS = [
    "stable_security_id", "ticker", "membership_start", "membership_end", "source", "as_of_date",
]


def load_point_in_time_membership(path: str | Path, *, source_name: str) -> pd.DataFrame:
    """Validate a WRDS/CRSP-style effective-date membership export."""
    path = Path(path)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    missing = set(FORMAL_MEMBERSHIP_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"membership export missing required columns: {sorted(missing)}")
    if frame["stable_security_id"].isna().any():
        raise ValueError("stable_security_id must not be missing")
    if frame["source"].astype(str).str.lower().eq("current_constituent_list").any():
        raise ValueError("current constituent lists cannot masquerade as point-in-time membership")
    for column in ("membership_start", "membership_end", "as_of_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    if frame["membership_start"].isna().any():
        raise ValueError("membership_start must be valid")
    if frame["membership_end"].notna().any() and (
        frame.loc[frame["membership_end"].notna(), "membership_end"]
        < frame.loc[frame["membership_end"].notna(), "membership_start"]
    ).any():
        raise ValueError("membership_end precedes membership_start")
    frame["source"] = source_name
    return frame.sort_values(["stable_security_id", "membership_start"]).reset_index(drop=True)


def membership_on_date(membership: pd.DataFrame, signal_date: str | pd.Timestamp) -> pd.DataFrame:
    date = pd.Timestamp(signal_date)
    active = membership["membership_start"].le(date) & (
        membership["membership_end"].isna() | membership["membership_end"].ge(date)
    )
    return membership.loc[active].copy()


def diagnostic_broad_membership(
    dates: pd.DatetimeIndex,
    close: pd.DataFrame,
    lagged_adv: pd.DataFrame,
    *,
    min_price: float = 5.0,
    min_lagged_adv: float = 5_000_000.0,
    min_history: int = 60,
) -> pd.DataFrame:
    history = close.notna().rolling(min_history, min_periods=min_history).sum().ge(min_history)
    eligible = close.ge(min_price) & lagged_adv.ge(min_lagged_adv) & history
    rows = []
    for date in dates:
        for ticker in close.columns:
            included = bool(eligible.loc[date, ticker])
            reason = "included" if included else (
                "price_below_threshold" if not close.loc[date, ticker] >= min_price
                else "liquidity_below_threshold" if not lagged_adv.loc[date, ticker] >= min_lagged_adv
                else "insufficient_price_history"
            )
            rows.append({"rebalance_date": date, "ticker": ticker, "included": included, "reason": reason})
    return pd.DataFrame(rows)


def point_in_time_market_cap(shares: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Use available shares and prior close; missing/non-positive inputs remain missing."""
    prior_close = close.shift(1)
    market_cap = shares.mul(prior_close)
    return market_cap.where(shares.gt(0) & prior_close.gt(0))


def diagnostic_small_cap_membership(
    broad_membership: pd.DataFrame,
    market_cap: pd.DataFrame,
    *,
    microcap_tail: float = 0.10,
    small_cap_share: float = 0.30,
) -> pd.DataFrame:
    if not 0 <= microcap_tail < 1 or not 0 < small_cap_share <= 1 - microcap_tail:
        raise ValueError("invalid small-cap percentile thresholds")
    rows = []
    for date, group in broad_membership.groupby("rebalance_date", sort=True):
        eligible = group.loc[group["included"], "ticker"]
        caps = market_cap.loc[pd.Timestamp(date), eligible].dropna()
        caps = caps.loc[caps.gt(0)].sort_values(kind="mergesort")
        ranks = caps.rank(method="first", pct=True)
        selected = set(ranks.loc[ranks.gt(microcap_tail) & ranks.le(microcap_tail + small_cap_share)].index)
        for ticker in group["ticker"]:
            included = ticker in selected
            cap = market_cap.loc[pd.Timestamp(date), ticker]
            reason = "included_small_cap" if included else (
                "not_broad_eligible" if ticker not in set(eligible)
                else "missing_or_nonpositive_market_cap" if pd.isna(cap) or cap <= 0
                else "excluded_microcap_tail" if ticker in set(ranks.loc[ranks.le(microcap_tail)].index)
                else "outside_small_cap_percentile"
            )
            rows.append({"rebalance_date": date, "ticker": ticker, "included": included, "reason": reason})
    return pd.DataFrame(rows)


def universe_manifest(
    universe_id: str, *, source_mode: str, status: str, labels: list[str], rule: str, member_counts: pd.Series
) -> dict[str, object]:
    return {
        "universe_id": universe_id,
        "version": UNIVERSE_VERSION,
        "source_mode": source_mode,
        "status": status,
        "labels": labels,
        "rule": rule,
        "member_count_min": int(member_counts.min()) if len(member_counts) else 0,
        "member_count_max": int(member_counts.max()) if len(member_counts) else 0,
        "member_count_latest": int(member_counts.iloc[-1]) if len(member_counts) else 0,
    }


def write_universe_outputs(output_root: str | Path, universe_id: str, membership: pd.DataFrame, manifest: dict) -> None:
    root = Path(output_root) / universe_id.lower()
    root.mkdir(parents=True, exist_ok=True)
    membership.to_csv(root / "membership_by_rebalance_date.csv", index=False)
    counts = membership.loc[membership["included"]].groupby("rebalance_date").size().rename("member_count")
    counts.to_csv(root / "member_counts.csv")
    reasons = membership.groupby(["included", "reason"]).size().rename("count").reset_index()
    reasons.to_csv(root / "inclusion_exclusion_summary.csv", index=False)
    quality = {
        "universe_id": universe_id,
        "membership_rows": int(len(membership)),
        "rebalance_dates": int(membership["rebalance_date"].nunique()) if "rebalance_date" in membership else 0,
        "included_rows": int(membership["included"].sum()) if "included" in membership else 0,
        "duplicate_membership_rows": int(
            membership.duplicated(["rebalance_date", "ticker"]).sum()
        ) if {"rebalance_date", "ticker"} <= set(membership.columns) else 0,
        "historical_sector_industry_status": "UNAVAILABLE_NOT_BACKFILLED",
    }
    (root / "data_quality_summary.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
