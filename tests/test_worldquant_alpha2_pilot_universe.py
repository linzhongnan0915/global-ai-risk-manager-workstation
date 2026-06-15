"""Unit tests for WorldQuant Alpha #2 pilot universe selection (Phase 1C.3B1)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.worldquant.pilot_universe import (
    PILOT_RANDOM_STATE,
    PILOT_SELECTION_REIT,
    PILOT_SELECTION_SPECIAL,
    build_pilot_universe_audit,
    select_pilot_universe,
)


def _research_frame() -> pd.DataFrame:
    rows = []
    exchanges = ["NASDAQ", "NYSE", "NYSE American", "BATS"]
    for idx in range(80):
        exchange = exchanges[idx % len(exchanges)]
        rows.append(
            {
                "symbol_raw": f"CS{idx:03d}",
                "symbol_normalized": f"CS{idx:03d}",
                "security_name": f"Common Stock Company {idx} - Common Stock",
                "listing_exchange": exchange,
                "classification": "common_stock",
                "is_reit": False,
                "is_adr": False,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            }
        )

    for symbol in ["REIT1", "REIT2", "REIT3"]:
        rows.append(
            {
                "symbol_raw": symbol,
                "symbol_normalized": symbol,
                "security_name": f"{symbol} REIT, Inc. Common Stock",
                "listing_exchange": "NYSE",
                "classification": "reit_common_equity",
                "is_reit": True,
                "is_adr": False,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            }
        )

    for symbol in ["BRK.A", "BRK-B", "SPE.C"]:
        rows.append(
            {
                "symbol_raw": symbol,
                "symbol_normalized": symbol.upper(),
                "security_name": f"{symbol} Special Format Common Stock",
                "listing_exchange": "NYSE",
                "classification": "common_stock",
                "is_reit": False,
                "is_adr": False,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            }
        )

    rows.extend(
        [
            {
                "symbol_raw": "ADR1",
                "symbol_normalized": "ADR1",
                "security_name": "ADR Example",
                "listing_exchange": "NYSE",
                "classification": "adr_depositary",
                "is_reit": False,
                "is_adr": True,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            },
            {
                "symbol_raw": "DUP1",
                "symbol_normalized": "DUP1",
                "security_name": "Duplicate Example",
                "listing_exchange": "NASDAQ",
                "classification": "common_stock",
                "is_reit": False,
                "is_adr": False,
                "eligible_candidate": True,
                "duplicate_symbol": True,
            },
            {
                "symbol_raw": "REVIEW1",
                "symbol_normalized": "REVIEW1",
                "security_name": "Needs Review Example",
                "listing_exchange": "NASDAQ",
                "classification": "needs_review_ambiguous",
                "is_reit": False,
                "is_adr": False,
                "eligible_candidate": False,
                "duplicate_symbol": False,
            },
        ]
    )
    return pd.DataFrame(rows)


def _eligible_research(research: pd.DataFrame) -> pd.DataFrame:
    return research.loc[
        research["eligible_candidate"].astype(bool)
        & ~research["duplicate_symbol"].astype(bool)
        & ~research["is_adr"].astype(bool)
        & research["classification"].isin(["common_stock", "reit_common_equity"])
    ].copy()


def test_pilot_universe_exact_size_and_reproducibility():
    research = _eligible_research(_research_frame())
    first = select_pilot_universe(research, sample_size=20, random_state=PILOT_RANDOM_STATE)
    second = select_pilot_universe(research, sample_size=20, random_state=PILOT_RANDOM_STATE)

    assert len(first) == 20
    pd.testing.assert_frame_equal(first, second)


def test_pilot_universe_retains_reits_and_special_symbols():
    research = _eligible_research(_research_frame())
    pilot = select_pilot_universe(research, sample_size=20, random_state=PILOT_RANDOM_STATE)

    assert set(research.loc[research["classification"] == "reit_common_equity", "symbol_normalized"]).issubset(
        set(pilot["symbol_normalized"])
    )
    assert {"BRK.A", "BRK-B", "SPE.C"}.issubset(set(pilot["symbol_normalized"]))
    assert set(pilot.loc[pilot["classification"] == "reit_common_equity", "pilot_selection_reason"]) == {
        PILOT_SELECTION_REIT
    }
    assert set(
        pilot.loc[pilot["symbol_normalized"].isin({"BRK.A", "BRK-B", "SPE.C"}), "pilot_selection_reason"]
    ) == {PILOT_SELECTION_SPECIAL}


def test_pilot_universe_excludes_ineligible_rows_from_input_validation():
    with pytest.raises(ValueError, match="fail pilot eligibility"):
        select_pilot_universe(_research_frame(), sample_size=20)


def test_pilot_universe_unique_symbols_and_no_adrs_or_duplicates():
    research = _eligible_research(_research_frame())
    pilot = select_pilot_universe(research, sample_size=20, random_state=PILOT_RANDOM_STATE)

    assert pilot["symbol_normalized"].is_unique
    assert not pilot["is_adr"].astype(bool).any()
    assert not pilot["duplicate_symbol"].astype(bool).any()
    assert pilot["eligible_candidate"].astype(bool).all()


def test_pilot_universe_stratified_sample_does_not_exceed_target_size():
    research = _eligible_research(_research_frame())
    pilot = select_pilot_universe(research, sample_size=25, random_state=PILOT_RANDOM_STATE)
    summary = build_pilot_universe_audit(research, pilot)

    assert summary["final_pilot_count"] == 25
    assert summary["reit_common_equity_count"] == 3
    assert summary["special_symbol_count"] == 3
    assert summary["common_stock_count"] == 22
    assert (pilot["pilot_selection_reason"] == "stratified_common_stock_sample").sum() == 19


def test_pilot_universe_rejects_sample_size_larger_than_available():
    research = _eligible_research(_research_frame())
    with pytest.raises(ValueError, match="exceeds available research-universe rows"):
        select_pilot_universe(research, sample_size=1000)
