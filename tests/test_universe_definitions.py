from __future__ import annotations

import pytest

from src.universe.universe_definitions import load_universe_config


def test_load_universe_definitions_yaml():
    config = load_universe_config("data/config/universe_definitions.yaml")
    assert config.global_settings["max_universe_size"] == 5000
    assert config.global_settings["chunk_size"] > 0
    assert config.global_settings["source_priority"][0] == "boss_provided_api"
    assert set(config.definitions) >= {
        "US_LARGE_CAP_CORE",
        "US_BROAD_MARKET",
        "US_SMALL_CAP",
        "US_ALL_COMMON_RESEARCH",
        "US_TRADABLE_LIQUID",
    }
    large = config.definitions["US_LARGE_CAP_CORE"]
    assert large.benchmark_family == "SP500_STYLE"
    assert "COMMON_STOCK" in large.include_asset_types
    assert "ETF" in large.exclude_asset_types


def test_reject_invalid_universe_definition(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
global_settings: {}
universes:
  BROKEN:
    description: Missing required fields.
    min_price: -1
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required"):
        load_universe_config(path)
