"""Research-universe policy for WorldQuant Alpha #2.

Security classification (``universe.py``) answers *what* a listing is.
This module answers whether a classified security is included in a given
Alpha #2 research universe version.

Research Universe v1
--------------------
Includes only non-ADR US common equity and REIT common equity that passed
security-master eligibility without duplicate symbols. No price, liquidity,
or history filters are applied at this stage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_RESEARCH_UNIVERSE_V1_OUTPUT = Path(
    "data/reference/worldquant_alpha2_research_universe_v1.csv"
)

RESEARCH_UNIVERSE_V1_CLASSIFICATIONS = frozenset({"common_stock", "reit_common_equity"})

RESEARCH_UNIVERSE_V1_COLUMNS = [
    "symbol_raw",
    "symbol_normalized",
    "security_name",
    "listing_exchange",
    "classification",
    "is_adr",
    "is_reit",
    "eligible_candidate",
    "duplicate_symbol",
]


def filter_research_universe_v1(master: pd.DataFrame) -> pd.DataFrame:
    """Apply Alpha #2 Research Universe v1 policy to a security master frame."""
    required = {"classification", "eligible_candidate", "duplicate_symbol", "is_adr"}
    missing = required - set(master.columns)
    if missing:
        raise ValueError(f"master is missing required columns: {sorted(missing)}")

    mask = (
        master["classification"].isin(RESEARCH_UNIVERSE_V1_CLASSIFICATIONS)
        & master["eligible_candidate"].astype(bool)
        & ~master["duplicate_symbol"].astype(bool)
        & ~master["is_adr"].astype(bool)
    )
    output_columns = [column for column in RESEARCH_UNIVERSE_V1_COLUMNS if column in master.columns]
    return master.loc[mask, output_columns].copy()


def build_research_universe_v1_audit(
    master: pd.DataFrame,
    candidates: pd.DataFrame,
) -> dict[str, Any]:
    """Summarize how Research Universe v1 differs from the candidate file."""
    research = filter_research_universe_v1(master)
    starting_candidates = candidates.copy()
    adr_excluded = starting_candidates.loc[starting_candidates["is_adr"].astype(bool)]
    duplicate_excluded = master.loc[
        master["eligible_candidate"].astype(bool) & master["duplicate_symbol"].astype(bool)
    ]

    return {
        "starting_candidate_count": int(len(starting_candidates)),
        "common_stock_count": int((research["classification"] == "common_stock").sum()),
        "reit_common_equity_count": int((research["classification"] == "reit_common_equity").sum()),
        "adrs_excluded_by_research_policy": int(len(adr_excluded)),
        "duplicates_excluded": int(len(duplicate_excluded)),
        "final_research_universe_v1_count": int(len(research)),
        "counts_by_listing_exchange": {
            exchange: int(count)
            for exchange, count in research["listing_exchange"].value_counts().sort_index().items()
        },
    }


def format_research_universe_v1_audit(summary: dict[str, Any]) -> str:
    lines = [
        "WorldQuant Alpha #2 Research Universe v1 audit",
        f"  Starting candidate count: {summary['starting_candidate_count']}",
        f"  Common-stock count: {summary['common_stock_count']}",
        f"  REIT common-equity count: {summary['reit_common_equity_count']}",
        f"  ADRs excluded by research policy: {summary['adrs_excluded_by_research_policy']}",
        f"  Duplicates excluded: {summary['duplicates_excluded']}",
        f"  Final Research Universe v1 count: {summary['final_research_universe_v1_count']}",
        "  Counts by listing exchange:",
    ]
    for exchange, count in summary["counts_by_listing_exchange"].items():
        lines.append(f"    - {exchange}: {count}")
    return "\n".join(lines)


def write_research_universe_v1(
    research_universe: pd.DataFrame,
    *,
    output_path: Path = DEFAULT_RESEARCH_UNIVERSE_V1_OUTPUT,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    research_universe.to_csv(output_path, index=False)
    return output_path
