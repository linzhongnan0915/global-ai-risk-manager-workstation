"""Tests for the current S&P 500 reference universe artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.generate_sp500_current_universe import build_artifact, normalize_constituents


ROOT = Path(__file__).resolve().parents[1]


def test_sp500_reference_artifact_shape_and_warning():
    artifact = json.loads((ROOT / "dashboard/data/universes/sp500_current.json").read_text(encoding="utf-8"))
    metadata = artifact["metadata"]
    rows = artifact["constituents"]

    assert metadata["provider"] == "Wikipedia"
    assert metadata["current_constituent_count"] == len(rows)
    assert len(rows) >= 500
    assert "survivorship-bias" in metadata["survivorship_bias_warning"]
    assert all(row["current_constituent"] is True for row in rows)
    assert {
        "ticker",
        "company_name",
        "sector",
        "industry",
        "source",
        "provider",
        "as_of_date",
        "current_constituent",
    } <= set(rows[0])


def test_sp500_generator_normalizes_fixture_without_live_network():
    frame = pd.DataFrame(
        [
            {
                "Symbol": "BRK.B",
                "Security": "Berkshire Hathaway",
                "GICS Sector": "Financials",
                "GICS Sub-Industry": "Multi-Sector Holdings",
            }
        ]
    )
    rows = normalize_constituents(frame, source_url="fixture://sp500", as_of_date="2026-06-17")
    artifact = build_artifact(rows, source_url="fixture://sp500", generated_at="2026-06-17T00:00:00+00:00")

    assert rows == [
        {
            "ticker": "BRK-B",
            "company_name": "Berkshire Hathaway",
            "sector": "Financials",
            "industry": "Multi-Sector Holdings",
            "source": "fixture://sp500",
            "provider": "Wikipedia",
            "as_of_date": "2026-06-17",
            "current_constituent": True,
        }
    ]
    assert artifact["metadata"]["current_constituent_count"] == 1
    assert artifact["metadata"]["survivorship_bias_warning"]
