"""Pilot-universe selection for WorldQuant Alpha #2 research validation.

This module selects a deterministic 500-security subset from Research
Universe v1 for ticker-mapping, download-batch, and data-quality testing.
It does not alter security classification or research-universe policy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_RESEARCH_UNIVERSE_V1_INPUT = Path(
    "data/reference/worldquant_alpha2_research_universe_v1.csv"
)
DEFAULT_PILOT_UNIVERSE_OUTPUT = Path(
    "data/reference/worldquant_alpha2_pilot_universe_500.csv"
)

PILOT_RANDOM_STATE = 42
DEFAULT_PILOT_SAMPLE_SIZE = 500

PILOT_UNIVERSE_COLUMNS = [
    "symbol_raw",
    "symbol_normalized",
    "security_name",
    "listing_exchange",
    "classification",
    "is_reit",
    "is_adr",
    "eligible_candidate",
    "duplicate_symbol",
    "pilot_selection_reason",
]

PILOT_SELECTION_REIT = "reit_inclusion"
PILOT_SELECTION_SPECIAL = "special_symbol_inclusion"
PILOT_SELECTION_STRATIFIED = "stratified_common_stock_sample"

_SPECIAL_SYMBOL_PATTERN = re.compile(r"[.-]")


def _has_special_symbol(symbol: str) -> bool:
    return bool(_SPECIAL_SYMBOL_PATTERN.search(str(symbol)))


def _validate_research_universe_input(research: pd.DataFrame) -> None:
    required = {
        "symbol_raw",
        "symbol_normalized",
        "security_name",
        "listing_exchange",
        "classification",
        "is_reit",
        "is_adr",
        "eligible_candidate",
        "duplicate_symbol",
    }
    missing = required - set(research.columns)
    if missing:
        raise ValueError(f"research universe is missing required columns: {sorted(missing)}")

    if research["symbol_normalized"].duplicated().any():
        raise ValueError("research universe contains duplicate symbol_normalized values")

    invalid = research[
        ~research["eligible_candidate"].astype(bool)
        | research["duplicate_symbol"].astype(bool)
        | research["is_adr"].astype(bool)
        | ~research["classification"].isin(["common_stock", "reit_common_equity"])
    ]
    if not invalid.empty:
        raise ValueError("research universe contains rows that fail pilot eligibility checks")


def load_research_universe_v1_csv(path: str | Path = DEFAULT_RESEARCH_UNIVERSE_V1_INPUT) -> pd.DataFrame:
    """Load Research Universe v1 from CSV."""
    return pd.read_csv(path)


def _allocate_stratum_sizes(counts: pd.Series, sample_size: int) -> dict[str, int]:
    if sample_size <= 0:
        return {exchange: 0 for exchange in counts.index}

    proportions = counts / counts.sum()
    allocation = (proportions * sample_size).apply(int)
    remainder = sample_size - int(allocation.sum())
    for exchange in proportions.sort_values(ascending=False).index:
        if remainder <= 0:
            break
        allocation[exchange] += 1
        remainder -= 1
    return {exchange: int(allocation[exchange]) for exchange in counts.index}


def _stratified_common_stock_sample(
    common_stock: pd.DataFrame,
    sample_size: int,
    *,
    random_state: int,
) -> pd.DataFrame:
    if sample_size <= 0:
        return common_stock.iloc[0:0].copy()
    if sample_size >= len(common_stock):
        if sample_size > len(common_stock):
            raise ValueError(
                f"requested {sample_size} common-stock rows but only {len(common_stock)} are available"
            )
        return common_stock.copy()

    counts = common_stock["listing_exchange"].value_counts()
    allocation = _allocate_stratum_sizes(counts, sample_size)

    selected_parts: list[pd.DataFrame] = []
    for exchange, target in allocation.items():
        if target <= 0:
            continue
        pool = common_stock.loc[common_stock["listing_exchange"] == exchange]
        draw = min(target, len(pool))
        selected_parts.append(pool.sample(n=draw, random_state=random_state))

    selected = pd.concat(selected_parts, ignore_index=False)
    if len(selected) < sample_size:
        remaining = common_stock.loc[~common_stock.index.isin(selected.index)]
        need = sample_size - len(selected)
        if need > len(remaining):
            raise ValueError(
                f"unable to fill stratified pilot sample: need {need} more rows but only "
                f"{len(remaining)} remain"
            )
        selected = pd.concat(
            [selected, remaining.sample(n=need, random_state=random_state)],
            ignore_index=False,
        )
    elif len(selected) > sample_size:
        selected = selected.sample(n=sample_size, random_state=random_state)

    return selected.sort_index()


def select_pilot_universe(
    research: pd.DataFrame,
    *,
    sample_size: int = DEFAULT_PILOT_SAMPLE_SIZE,
    random_state: int = PILOT_RANDOM_STATE,
) -> pd.DataFrame:
    """Select a deterministic pilot universe from Research Universe v1."""
    _validate_research_universe_input(research)

    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if sample_size > len(research):
        raise ValueError(
            f"requested pilot sample size {sample_size} exceeds available research-universe rows "
            f"({len(research)})"
        )

    working = research.copy()
    selected_rows: list[pd.Series] = []

    reits = working.loc[working["classification"] == "reit_common_equity"].sort_values(
        ["symbol_normalized", "symbol_raw"]
    )
    for _, row in reits.iterrows():
        enriched = row.copy()
        enriched["pilot_selection_reason"] = PILOT_SELECTION_REIT
        selected_rows.append(enriched)

    selected_symbols = {row["symbol_normalized"] for row in selected_rows}
    remaining = working.loc[~working["symbol_normalized"].isin(selected_symbols)]

    special_mask = remaining["symbol_raw"].map(_has_special_symbol) | remaining["symbol_normalized"].map(
        _has_special_symbol
    )
    specials = remaining.loc[special_mask].sort_values(["symbol_normalized", "symbol_raw"])
    for _, row in specials.iterrows():
        enriched = row.copy()
        enriched["pilot_selection_reason"] = PILOT_SELECTION_SPECIAL
        selected_rows.append(enriched)

    selected_symbols = {row["symbol_normalized"] for row in selected_rows}
    remaining = working.loc[~working["symbol_normalized"].isin(selected_symbols)]
    common_remaining = remaining.loc[remaining["classification"] == "common_stock"]

    slots_left = sample_size - len(selected_rows)
    if slots_left > 0:
        stratified = _stratified_common_stock_sample(
            common_remaining,
            slots_left,
            random_state=random_state,
        )
        for _, row in stratified.iterrows():
            enriched = row.copy()
            enriched["pilot_selection_reason"] = PILOT_SELECTION_STRATIFIED
            selected_rows.append(enriched)

    pilot = pd.DataFrame(selected_rows).reset_index(drop=True)
    if len(pilot) != sample_size:
        raise ValueError(
            f"pilot selection produced {len(pilot)} rows but expected exactly {sample_size}"
        )

    return pilot[PILOT_UNIVERSE_COLUMNS]


def build_pilot_universe_audit(
    research: pd.DataFrame,
    pilot: pd.DataFrame,
    *,
    random_state: int = PILOT_RANDOM_STATE,
) -> dict[str, Any]:
    special_mask = pilot["symbol_raw"].map(_has_special_symbol) | pilot["symbol_normalized"].map(
        _has_special_symbol
    )
    return {
        "source_research_universe_count": int(len(research)),
        "final_pilot_count": int(len(pilot)),
        "unique_symbol_count": int(pilot["symbol_normalized"].nunique()),
        "common_stock_count": int((pilot["classification"] == "common_stock").sum()),
        "reit_common_equity_count": int((pilot["classification"] == "reit_common_equity").sum()),
        "special_symbol_count": int(special_mask.sum()),
        "counts_by_listing_exchange": {
            exchange: int(count)
            for exchange, count in pilot["listing_exchange"].value_counts().sort_index().items()
        },
        "counts_by_pilot_selection_reason": {
            reason: int(count)
            for reason, count in pilot["pilot_selection_reason"].value_counts().sort_index().items()
        },
        "random_state": random_state,
    }


def format_pilot_universe_audit(summary: dict[str, Any]) -> str:
    lines = [
        "WorldQuant Alpha #2 pilot universe audit",
        f"  Source research-universe count: {summary['source_research_universe_count']}",
        f"  Final pilot count: {summary['final_pilot_count']}",
        f"  Unique-symbol count: {summary['unique_symbol_count']}",
        f"  Common-stock count: {summary['common_stock_count']}",
        f"  REIT common-equity count: {summary['reit_common_equity_count']}",
        f"  Special-symbol count: {summary['special_symbol_count']}",
        f"  Random seed used: {summary['random_state']}",
        "  Counts by listing exchange:",
    ]
    for exchange, count in summary["counts_by_listing_exchange"].items():
        lines.append(f"    - {exchange}: {count}")
    lines.append("  Counts by pilot selection reason:")
    for reason, count in summary["counts_by_pilot_selection_reason"].items():
        lines.append(f"    - {reason}: {count}")
    return "\n".join(lines)


def write_pilot_universe(
    pilot: pd.DataFrame,
    *,
    output_path: Path = DEFAULT_PILOT_UNIVERSE_OUTPUT,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pilot.to_csv(output_path, index=False)
    return output_path


def build_pilot_universe_from_csv(
    *,
    input_path: Path = DEFAULT_RESEARCH_UNIVERSE_V1_INPUT,
    output_path: Path = DEFAULT_PILOT_UNIVERSE_OUTPUT,
    sample_size: int = DEFAULT_PILOT_SAMPLE_SIZE,
    random_state: int = PILOT_RANDOM_STATE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    research = load_research_universe_v1_csv(input_path)
    pilot = select_pilot_universe(research, sample_size=sample_size, random_state=random_state)
    summary = build_pilot_universe_audit(research, pilot, random_state=random_state)
    write_pilot_universe(pilot, output_path=output_path)
    return pilot, summary
