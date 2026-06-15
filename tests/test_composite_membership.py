"""Tests for dynamic Combined Portfolio membership (equal-weight 1/N)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.strategy_factory_research_adapter import COMPOSITE_ID, build_factory_research_catalog
from src.strategies.composite_membership import (
    composite_membership_for,
    composite_weights,
    eligible_composite_constituent_ids,
    equal_composite_weight,
    passes_composite_gate,
)
from src.strategies.platform_registry import DEPRECATED_HISTORICAL_PLATFORM_MEMBER_IDS, RAPID_BACKTEST_IDS
from src.strategies.rapid_20plus1 import build_equal_weight_composite, resolve_composite_active_ids

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTORY_ROOT = PROJECT_ROOT / "output/research/strategy_factory_v1"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/rapid_20plus1"
BUNDLE_PATH = PROJECT_ROOT / "dashboard/data/us_equity_research_bundle.json"


@pytest.fixture(scope="module")
def catalog() -> dict:
    return build_factory_research_catalog(PROJECT_ROOT)


def _research_composite_members(catalog: dict) -> list[dict]:
    return [
        row
        for row in catalog["results"]
        if row["strategy_id"] != COMPOSITE_ID
        and row["backtest"]["factory_research"].get("research_composite_eligible")
    ]


def test_passes_composite_gate_requires_positive_net_and_sharpe() -> None:
    assert passes_composite_gate({"run_valid": True, "cumulative_net_return": 0.01, "net_sharpe": 0.1})
    assert not passes_composite_gate({"run_valid": True, "cumulative_net_return": 0.01, "net_sharpe": -0.1})
    assert not passes_composite_gate({"run_valid": False, "cumulative_net_return": 0.01, "net_sharpe": 0.1})


def test_equal_weight_math_examples() -> None:
    assert equal_composite_weight(13) == pytest.approx(1 / 13)
    assert equal_composite_weight(20) == pytest.approx(0.05)
    assert equal_composite_weight(40) == pytest.approx(0.025)
    assert equal_composite_weight(50) == pytest.approx(0.02)


def test_dynamic_membership_synthetic_add_and_remove() -> None:
    summaries = {
        "A": {"run_valid": True, "cumulative_net_return": 0.10, "net_sharpe": 0.50},
        "B": {"run_valid": True, "cumulative_net_return": 0.08, "net_sharpe": 0.40},
        "C": {"run_valid": True, "cumulative_net_return": 0.05, "net_sharpe": 0.20},
        "D": {"run_valid": True, "cumulative_net_return": 0.04, "net_sharpe": 0.15},
    }

    def eligible(ids: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(strategy_id for strategy_id in ids if passes_composite_gate(summaries[strategy_id])))

    first = eligible(("A", "B", "C"))
    assert first == ("A", "B", "C")
    assert equal_composite_weight(len(first)) == pytest.approx(1 / 3)

    second = eligible(("A", "B", "C", "D"))
    assert second == ("A", "B", "C", "D")
    assert equal_composite_weight(len(second)) == pytest.approx(0.25)

    summaries["C"] = {"run_valid": True, "cumulative_net_return": -0.01, "net_sharpe": 0.10}
    third = eligible(("A", "B", "C", "D"))
    assert third == ("A", "B", "D")
    assert equal_composite_weight(len(third)) == pytest.approx(1 / 3)


def test_composite_excludes_itself() -> None:
    assert composite_membership_for(COMPOSITE_ID, {"A"}) == "REFERENCE_ONLY"


def test_composite_weights_sum_to_one() -> None:
    ids = ("A", "B", "C", "D")
    weights = composite_weights(ids)
    assert pytest.approx(sum(weights.values())) == 1.0
    assert all(weight == pytest.approx(0.25) for weight in weights.values())


@pytest.mark.skipif(not FACTORY_ROOT.exists(), reason="factory outputs missing")
def test_runtime_constituents_use_eligibility_gate_not_deprecated_list() -> None:
    eligible = eligible_composite_constituent_ids(FACTORY_ROOT)
    active_ids, notes = resolve_composite_active_ids(FACTORY_ROOT, pd.DataFrame())
    assert notes == []
    assert active_ids == eligible
    assert len(eligible) != len(DEPRECATED_HISTORICAL_PLATFORM_MEMBER_IDS)
    assert set(eligible) != set(DEPRECATED_HISTORICAL_PLATFORM_MEMBER_IDS)


@pytest.mark.skipif(not FACTORY_ROOT.exists(), reason="factory outputs missing")
def test_eligible_ids_match_composite_gate_on_registry() -> None:
    eligible = eligible_composite_constituent_ids(FACTORY_ROOT)
    assert COMPOSITE_ID not in eligible
    assert all(strategy_id in RAPID_BACKTEST_IDS for strategy_id in eligible)
    assert len(eligible) >= 1


@pytest.mark.skipif(not (ARTIFACT_ROOT / "combined_portfolio_summary.json").exists(), reason="composite missing")
def test_composite_summary_matches_eligible_registry_ids() -> None:
    summary = json.loads((ARTIFACT_ROOT / "combined_portfolio_summary.json").read_text(encoding="utf-8"))
    eligible = eligible_composite_constituent_ids(FACTORY_ROOT)
    assert set(summary["constituent_ids"]) == set(eligible)
    assert summary["N"] == len(eligible)
    assert pytest.approx(summary["equal_weight"]) == equal_composite_weight(len(eligible))
    assert summary.get("dynamic_membership") is True


def test_catalog_composite_membership_is_dynamic(catalog: dict) -> None:
    composite = next(row for row in catalog["results"] if row["strategy_id"] == COMPOSITE_ID)
    payload = composite["backtest"]["factory_research"]["combined_portfolio"]
    active_members = _research_composite_members(catalog)
    assert set(payload["constituent_ids"]) == {row["strategy_id"] for row in active_members}
    assert payload["N"] == len(active_members)
    assert pytest.approx(sum(payload["weights"].values())) == 1.0
    assert all(weight == pytest.approx(equal_composite_weight(payload["N"])) for weight in payload["weights"].values())
    assert "C3A1_010" not in payload["constituent_ids"]
    assert payload.get("target_platform_slots") is None
    assert payload.get("target_equal_weight") is None
    arch = catalog["architecture"]
    assert arch["dynamic_membership"] is True
    assert arch["live_allocation_approved"] is False
    assert arch["composite_constituent_count"] == len(active_members)
    assert pytest.approx(arch["composite_equal_weight"]) == equal_composite_weight(len(active_members))
    assert "target_underlying_count" not in arch


def test_research_eligibility_is_explicit_and_not_live_allocation(catalog: dict) -> None:
    active_members = _research_composite_members(catalog)
    assert active_members
    for row in active_members:
        factory = row["backtest"]["factory_research"]
        backtest = row["backtest"]
        assert factory["research_composite_eligible"] is True
        assert factory["live_allocation_approved"] is False
        assert backtest["live_allocation_approved"] is False
        assert backtest["allocation_eligible"] is False


@pytest.mark.skipif(not BUNDLE_PATH.exists(), reason="dashboard bundle missing")
def test_bundle_architecture_is_dynamic_not_fixed_target() -> None:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    arch = payload["factory_strategy_research"]["architecture"]
    assert arch["dynamic_membership"] is True
    assert arch["live_allocation_approved"] is False
    assert "target_underlying_count" not in arch
    composite = next(
        row for row in payload["factory_strategy_research"]["results"] if row["strategy_id"] == COMPOSITE_ID
    )["backtest"]["factory_research"]["combined_portfolio"]
    assert composite.get("eligible_member_ids") == composite.get("constituent_ids")


def test_build_equal_weight_composite_unit() -> None:
    columns = ["A", "B", "C", "D"]
    data = {col: [0.001, 0.002, -0.001] for col in columns}
    gross = pd.DataFrame(data, index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    net = gross - 0.0001
    _, summary = build_equal_weight_composite(gross, net)
    assert summary["N"] == 4
    assert pytest.approx(summary["equal_weight"]) == 0.25
    assert summary.get("dynamic_membership") is True
