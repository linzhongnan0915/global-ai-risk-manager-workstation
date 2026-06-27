from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.test_universe_file_provider import write_valid_provider_inputs

ROOT = Path(__file__).resolve().parents[1]


def test_refresh_script_writes_expected_artifacts(tmp_path: Path):
    input_dir = tmp_path / "provider_inputs"
    output_dir = tmp_path / "data/universe"
    write_valid_provider_inputs(input_dir)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/refresh_universe.py",
            "--provider",
            "file",
            "--input-dir",
            str(input_dir),
            "--as-of-date",
            "2026-06-22",
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Universe refresh complete" in result.stdout
    snapshot = json.loads((output_dir / "current_universe_snapshot.json").read_text(encoding="utf-8"))
    quality = json.loads((output_dir / "universe_quality_report.json").read_text(encoding="utf-8"))

    assert snapshot["source_status"] == "LOADED_FILE_PROVIDER"
    assert snapshot["universes"]["US_LARGE_CAP_CORE"]["included_count"] == 1
    assert snapshot["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
    assert quality["provider_status"]["status"] == "LOADED_FILE_PROVIDER"
    assert (output_dir / "security_master.csv").exists()
    assert (output_dir / "universe_membership.csv").exists()
    assert (output_dir / "universe_refresh_log.jsonl").exists()


def test_refresh_script_reports_contract_failure(tmp_path: Path):
    input_dir = tmp_path / "provider_inputs"
    input_dir.mkdir()
    (input_dir / "security_master.csv").write_text(
        "security_id,ticker,company_name\nSEC-A,AAA,Alpha Provider Corp\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/refresh_universe.py",
            "--provider",
            "file",
            "--input-dir",
            str(input_dir),
            "--as-of-date",
            "2026-06-22",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 2
    assert "security_master missing required columns" in result.stderr
