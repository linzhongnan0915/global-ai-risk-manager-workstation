from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _missing(*relative_paths: str) -> list[str]:
    return [path for path in relative_paths if not (ROOT / path).exists()]


def _bundle_is_current() -> bool:
    path = ROOT / "dashboard/data/us_equity_research_bundle.json"
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    research = payload.get("factory_strategy_research") or {}
    results = research.get("results") or []
    return research.get("results_count") == 32 and len(results) == 32


def pytest_runtest_setup(item: pytest.Item) -> None:
    nodeid = item.nodeid.replace("\\", "/")

    generated_requirements: list[tuple[str, tuple[str, ...], str]] = [
        (
            "tests/test_strategy_factory_research_adapter.py",
            ("output/research/strategy_factory_v1", "output/research/strategy_21_research_composite_v1"),
            "python scripts/run_rapid_20plus1.py",
        ),
        (
            "tests/test_diverse_strategy_outputs.py",
            ("output/research/universe_foundation_diverse_strategy_v1/candidate_summary.csv",),
            "python -m src.strategies.diverse_strategy_research",
        ),
        (
            "tests/test_event_panel_research.py",
            ("output/research/event_panel_final_four_strategy_batch_v1/candidate_summary.csv",),
            "python -m src.strategies.event_panel_research",
        ),
        (
            "tests/test_final_challenge_research.py",
            ("output/research/final_strict_challenge_batch_v1/candidate_summary.csv",),
            "python -m src.strategies.final_challenge_research",
        ),
        (
            "tests/test_final_delivery_research.py",
            ("output/research/final_platform_delivery_v1/candidate_summary.csv",),
            "python -m src.strategies.final_delivery_research",
        ),
        (
            "tests/test_final_strategy_research.py::test_final_research_outputs_are_research_only_and_reconciled",
            (
                "output/research/final_strategy_research_v1/run_manifest.json",
                "output/research/final_fundamental_research_v1/trade_log.csv",
            ),
            "python scripts/run_final_strategy_research.py",
        ),
        (
            "tests/test_strategy_selection_expansion.py",
            ("output/research/final_fundamental_research_v1/candidate_summary.csv",),
            "python scripts/build_strategy_selection_expansion_bundle.py",
        ),
    ]
    for pattern, paths, generator in generated_requirements:
        if pattern in nodeid:
            missing = _missing(*paths)
            if missing:
                pytest.skip(
                    "generated research artifact prerequisite missing: "
                    + ", ".join(missing)
                    + f"; source generator: {generator}"
                )

    if (
        "tests/test_composite_membership.py::test_catalog_" in nodeid
        or "tests/test_composite_membership.py::test_research_eligibility" in nodeid
    ):
        missing = _missing("output/research/strategy_factory_v1", "output/research/strategy_21_research_composite_v1")
        if missing:
            pytest.skip(
                "generated strategy factory research prerequisites missing: "
                + ", ".join(missing)
                + "; source generator: python scripts/run_rapid_20plus1.py"
            )

    if "tests/test_rapid_20plus1.py::test_bundle_has_all_underlying_plus_composite" in nodeid and not _bundle_is_current():
        pytest.skip(
            "dashboard research bundle is absent or stale; source generator: python scripts/build_us_equity_dashboard_bundle.py"
        )

    if "tests/test_shadow_live_operations.py::test_generated_raw_outputs_reconcile" in nodeid:
        missing = _missing("output/shadow_live/daily_run_manifest.json", "output/shadow_live/trade_log.csv")
        if missing:
            pytest.skip(
                "generated shadow-live outputs missing: "
                + ", ".join(missing)
                + "; source generator: python scripts/run_shadow_live_daily.py"
            )

    if "tests/test_shadow_live_operations.py::test_segment_continuity_and_exit_only_contract" in nodeid:
        missing = _missing("output/shadow_live/portfolio_daily_ledger.csv", "output/shadow_live/daily_run_manifest.json")
        if missing:
            pytest.skip(
                "generated shadow-live ledger missing: "
                + ", ".join(missing)
                + "; source generator: python scripts/run_shadow_live_daily.py"
            )
