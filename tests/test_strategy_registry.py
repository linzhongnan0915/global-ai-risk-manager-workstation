from pathlib import Path

from src.strategies.registry import load_strategy_registry, registry_weights


def test_strategy_registry_loading():
    records = load_strategy_registry(Path("data/config/strategy_registry.json"))

    assert len(records) == 20
    assert records[0].strategy_id == "STRAT_001"
    assert records[0].target_weight == 0.05


def test_registry_weights_sum_to_one():
    records = load_strategy_registry(Path("data/config/strategy_registry.json"))
    weights = registry_weights(records)

    assert round(sum(weights.values()), 10) == 1.0

