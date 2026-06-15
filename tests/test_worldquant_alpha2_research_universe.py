"""Unit tests for WorldQuant Alpha #2 Research Universe v1 policy (Phase 1C.3A)."""

from __future__ import annotations

import pandas as pd

from src.strategies.worldquant.research_universe import (
    build_research_universe_v1_audit,
    filter_research_universe_v1,
)


def _sample_master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol_raw": "AAPL",
                "symbol_normalized": "AAPL",
                "security_name": "Apple Inc. - Common Stock",
                "listing_exchange": "NASDAQ",
                "classification": "common_stock",
                "is_adr": False,
                "is_reit": False,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            },
            {
                "symbol_raw": "GOOD",
                "symbol_normalized": "GOOD",
                "security_name": "Gladstone Commercial Corporation - Real Estate Investment Trust",
                "listing_exchange": "NASDAQ",
                "classification": "reit_common_equity",
                "is_adr": False,
                "is_reit": True,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            },
            {
                "symbol_raw": "ZTO",
                "symbol_normalized": "ZTO",
                "security_name": "ZTO Express (Cayman) Inc. American Depositary Shares",
                "listing_exchange": "NYSE",
                "classification": "adr_depositary",
                "is_adr": True,
                "is_reit": False,
                "eligible_candidate": True,
                "duplicate_symbol": False,
            },
            {
                "symbol_raw": "DUP",
                "symbol_normalized": "DUP",
                "security_name": "Duplicate Symbol Test - Common Stock",
                "listing_exchange": "NASDAQ",
                "classification": "common_stock",
                "is_adr": False,
                "is_reit": False,
                "eligible_candidate": True,
                "duplicate_symbol": True,
            },
            {
                "symbol_raw": "COOP",
                "symbol_normalized": "COOP",
                "security_name": "Ambiguous Operating Company Inc.",
                "listing_exchange": "NASDAQ",
                "classification": "needs_review_ambiguous",
                "is_adr": False,
                "is_reit": False,
                "eligible_candidate": False,
                "duplicate_symbol": False,
            },
            {
                "symbol_raw": "RNP",
                "symbol_normalized": "RNP",
                "security_name": "Cohen & Steers REIT and Preferred and Income Fund, Inc. Common Shares",
                "listing_exchange": "NYSE",
                "classification": "closed_end_fund",
                "is_adr": False,
                "is_reit": False,
                "eligible_candidate": False,
                "duplicate_symbol": False,
            },
        ]
    )


def test_research_universe_v1_includes_common_stock_and_reit_equity():
    research = filter_research_universe_v1(_sample_master())

    assert set(research["symbol_normalized"]) == {"AAPL", "GOOD"}
    assert research.loc[research["symbol_normalized"] == "AAPL", "classification"].iloc[0] == "common_stock"
    assert research.loc[research["symbol_normalized"] == "GOOD", "classification"].iloc[0] == "reit_common_equity"


def test_research_universe_v1_excludes_adr_duplicate_needs_review_and_ineligible():
    research = filter_research_universe_v1(_sample_master())
    excluded = {"ZTO", "DUP", "COOP", "RNP"}

    assert excluded.isdisjoint(set(research["symbol_normalized"]))


def test_research_universe_v1_audit_summary():
    master = _sample_master()
    candidates = master.loc[master["eligible_candidate"].astype(bool) & ~master["duplicate_symbol"].astype(bool)]
    summary = build_research_universe_v1_audit(master, candidates)

    assert summary["starting_candidate_count"] == 3
    assert summary["common_stock_count"] == 1
    assert summary["reit_common_equity_count"] == 1
    assert summary["adrs_excluded_by_research_policy"] == 1
    assert summary["duplicates_excluded"] == 1
    assert summary["final_research_universe_v1_count"] == 2
    assert summary["counts_by_listing_exchange"] == {"NASDAQ": 2}
