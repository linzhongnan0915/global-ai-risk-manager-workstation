from __future__ import annotations

from pathlib import Path

from src.universe.file_provider import FileUniverseProvider
from src.universe.universe_builder import UniverseBuilder
from src.universe.universe_refresh_service import universe_members_payload, universe_summary_payload
from tests.test_universe_file_provider import write_valid_provider_inputs

ROOT = Path(__file__).resolve().parents[1]


def test_api_payload_returns_universe_summary_after_refresh(tmp_path: Path):
    input_dir = tmp_path / "provider_inputs"
    write_valid_provider_inputs(input_dir)
    UniverseBuilder(
        root=ROOT,
        output_dir=tmp_path / "data/universe",
        provider=FileUniverseProvider(input_dir),
    ).build(as_of_date="2026-06-22")

    summary = universe_summary_payload(tmp_path)
    members = universe_members_payload(tmp_path, universe_name="US_LARGE_CAP_CORE")

    assert summary["ok"] is True
    assert summary["source_status"] == "LOADED_FILE_PROVIDER"
    assert summary["universes"]["US_LARGE_CAP_CORE"]["included_count"] == 1
    assert summary["universes"]["US_LARGE_CAP_CORE"]["excluded_by_reason"]["missing_price"] == 1
    assert summary["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
    assert "AAA" in members["members"]
    assert members["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"


def test_api_payload_handles_zero_count_universe_state(tmp_path: Path):
    output_dir = tmp_path / "data/universe"
    builder = UniverseBuilder(
        root=ROOT,
        output_dir=output_dir,
        provider=FileUniverseProvider(tmp_path / "missing_provider_inputs"),
    )
    builder.build(as_of_date="2026-06-22")

    summary = universe_summary_payload(tmp_path)

    assert summary["ok"] is True
    assert summary["source_status"] == "UNAVAILABLE"
    assert summary["universes"]["US_LARGE_CAP_CORE"]["included_count"] == 0
    assert summary["universes"]["US_LARGE_CAP_CORE"]["total_candidates"] == 0
    assert summary["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
