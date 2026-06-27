from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts import refresh_universe
from src.universe.yfinance_provider import DATA_SOURCE, YFinanceProvisionalUniverseProvider
from tests.test_yfinance_provisional_provider import FakeYFinance, _price_frame, _write_reference_inputs

ROOT = Path(__file__).resolve().parents[1]


def _copy_universe_config(root: Path) -> None:
    config_dir = root / "data" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "data" / "config" / "universe_definitions.yaml", config_dir / "universe_definitions.yaml")


def test_refresh_command_runs_yfinance_provisional_with_mocked_provider(tmp_path: Path, monkeypatch):
    _copy_universe_config(tmp_path)
    _write_reference_inputs(tmp_path, tickers=("AAA", "BBB"))
    fake = FakeYFinance(
        _price_frame(["AAA", "BBB"]),
        {
            "AAA": {"market_cap": 100_000_000_000, "sector": "Technology", "industry": "Software"},
            "BBB": {"market_cap": 5_000_000_000, "sector": "Industrials", "industry": "Machinery"},
        },
    )

    class MockedYFinanceProvider(YFinanceProvisionalUniverseProvider):
        def __init__(self, root, **kwargs):
            kwargs["yfinance_module"] = fake
            kwargs["allow_symbol_directory_download"] = False
            kwargs["definitions_path"] = tmp_path / "data" / "config" / "universe_definitions.yaml"
            kwargs["force_refresh"] = True
            kwargs["use_cache"] = False
            super().__init__(
                root,
                **kwargs,
            )

    monkeypatch.setattr(refresh_universe, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(refresh_universe, "YFinanceProvisionalUniverseProvider", MockedYFinanceProvider)

    output_dir = tmp_path / "out" / "universe"
    code = refresh_universe.main(
        [
            "--provider",
            "yfinance-provisional",
            "--universe",
            "US_BROAD_MARKET",
            "--max-tickers",
            "2",
            "--as-of-date",
            "2026-06-22",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert code == 0
    snapshot = json.loads((output_dir / "current_universe_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["data_source"] == DATA_SOURCE
    assert snapshot["universes"]["US_BROAD_MARKET"]["total_candidates"] == 2
    assert snapshot["universes"]["US_BROAD_MARKET"]["included_count"] == 2
    assert (tmp_path / "data" / "universe" / "yfinance_provisional_diagnostics.json").exists()
    report = tmp_path / "docs" / "YFINANCE_PROVISIONAL_UNIVERSE_COVERAGE_REPORT.md"
    assert report.exists()
    assert "not survivor-bias-free" in report.read_text(encoding="utf-8")


def test_yfinance_refresh_does_not_use_provider_template_rows(tmp_path: Path, monkeypatch):
    _copy_universe_config(tmp_path)
    template_dir = tmp_path / "data" / "provider_inputs" / "universe" / "templates"
    template_dir.mkdir(parents=True)
    (template_dir / "security_master.csv").write_text(
        "security_id,ticker,company_name\nSAMPLE-SEC-001,SAMP_A,Sample Template Alpha Corp\n",
        encoding="utf-8",
    )
    fake = FakeYFinance(_price_frame(["SAMP_A"]), {"SAMP_A": {"market_cap": 1_000_000_000}})

    class MockedYFinanceProvider(YFinanceProvisionalUniverseProvider):
        def __init__(self, root, **kwargs):
            kwargs["yfinance_module"] = fake
            kwargs["allow_symbol_directory_download"] = False
            kwargs["definitions_path"] = tmp_path / "data" / "config" / "universe_definitions.yaml"
            kwargs["force_refresh"] = True
            kwargs["use_cache"] = False
            super().__init__(
                root,
                **kwargs,
            )

    monkeypatch.setattr(refresh_universe, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(refresh_universe, "YFinanceProvisionalUniverseProvider", MockedYFinanceProvider)

    output_dir = tmp_path / "out" / "universe"
    code = refresh_universe.main(
        [
            "--provider",
            "yfinance-provisional",
            "--universe",
            "US_BROAD_MARKET",
            "--as-of-date",
            "2026-06-22",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert code == 0
    snapshot = json.loads((output_dir / "current_universe_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["source_status"] == "UNAVAILABLE_NO_CURRENT_LISTED_CANDIDATES"
    assert snapshot["universes"]["US_BROAD_MARKET"]["total_candidates"] == 0
    assert "SAMP_A" not in (output_dir / "security_master.csv").read_text(encoding="utf-8")
