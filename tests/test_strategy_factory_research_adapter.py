from __future__ import annotations

from pathlib import Path

import pytest

from src.reporting.strategy_factory_research_adapter import (
    COMPOSITE_ID,
    FACTORY_STRATEGY_IDS,
    build_factory_research_catalog,
)
from src.strategies.composite_membership import equal_composite_weight
from src.strategies.platform_registry import COMPOSITE_ID as REGISTRY_COMPOSITE_ID, RAPID_BACKTEST_IDS
from src.strategies.rapid_20plus1 import build_equal_weight_composite


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog() -> dict:
    return build_factory_research_catalog(PROJECT_ROOT)


def _research_composite_members(catalog: dict) -> list[dict]:
    return [
        row
        for row in catalog["results"]
        if row["backtest"]["factory_research"].get("research_composite_eligible")
    ]


def test_catalog_contains_all_underlying_strategies_and_composite(catalog: dict) -> None:
    ids = [item["strategy_id"] for item in catalog["results"]]
    assert ids == list(RAPID_BACKTEST_IDS) + [COMPOSITE_ID]
    assert set(FACTORY_STRATEGY_IDS) == set(RAPID_BACKTEST_IDS)
    assert catalog["results_count"] == len(RAPID_BACKTEST_IDS) + 1


def test_default_strategy_has_full_research_payload(catalog: dict) -> None:
    item = next(row for row in catalog["results"] if row["strategy_id"] == "C2A2_020")
    backtest = item["backtest"]
    assert len(backtest["return_series"]["dates"]) > 100
    assert backtest["factory_research"]["research_composite_eligible"] is True
    assert backtest["factory_research"]["live_allocation_approved"] is False


def test_combined_portfolio_uses_only_research_composite_members(catalog: dict) -> None:
    item = next(row for row in catalog["results"] if row["strategy_id"] == COMPOSITE_ID)
    composite = item["backtest"]["factory_research"]["combined_portfolio"]
    active_members = _research_composite_members(catalog)
    active_count = len(active_members)
    assert composite["N"] == active_count
    assert active_count >= 1
    assert pytest.approx(sum(composite["weights"].values())) == 1.0
    assert all(weight == pytest.approx(equal_composite_weight(composite["N"])) for weight in composite["weights"].values())
    assert "C3A1_010" not in composite["constituent_ids"]
    assert item["research_group"] == "COMBINED_PORTFOLIO"
    assert composite.get("dynamic_membership") is True
    assert item["backtest"]["live_allocation_approved"] is False


def test_reference_strategy_marked_reference_only(catalog: dict) -> None:
    item = next(row for row in catalog["results"] if row["strategy_id"] == "C3A1_010")
    assert item["research_group"] == "REFERENCE_US_EQUITY_RESEARCH"
    assert item["backtest"]["lifecycle_status"] == "REFERENCE ONLY"
    assert item["backtest"]["factory_research"]["research_composite_eligible"] is False
    assert item["backtest"]["factory_research"]["live_allocation_approved"] is False


def test_catalog_architecture_documents_dynamic_pool(catalog: dict) -> None:
    arch = catalog["architecture"]
    active_members = _research_composite_members(catalog)
    assert arch["dynamic_membership"] is True
    assert arch["live_allocation_approved"] is False
    assert arch["eligible_active_count"] == len(active_members)
    assert arch["composite_constituent_count"] == len(active_members)
    assert pytest.approx(arch["composite_equal_weight"]) == equal_composite_weight(len(active_members))
    assert "target_underlying_count" not in arch


def test_composite_id_is_canonical() -> None:
    assert COMPOSITE_ID == REGISTRY_COMPOSITE_ID == "COMBINED_PORTFOLIO_V1"
