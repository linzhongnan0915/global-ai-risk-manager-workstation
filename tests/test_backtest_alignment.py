"""Backtest alignment and missing-data policy regression tests."""

from __future__ import annotations

import pandas as pd

from src.portfolio.return_alignment import align_strategy_series, align_strategy_series_for_weights


def _series(values: list[float], start: str = "2026-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=index, dtype=float)


def test_alignment_drops_missing_dates_without_fillna():
    series_map = {
        "A": _series([0.01, 0.02, 0.03]),
        "B": _series([0.01, 0.02], start="2026-01-02"),
    }
    aligned = align_strategy_series(series_map, ["A", "B"])
    assert aligned.observations == 2
    assert aligned.dates == ["2026-01-02", "2026-01-03"]
    assert aligned.returns_by_strategy["A"] == [0.02, 0.03]


def test_weighted_alignment_uses_only_nonzero_strategies():
    series_map = {
        "A": _series([0.01] * 5),
        "B": _series([0.02] * 5),
        "C": _series([0.03] * 5),
    }
    aligned = align_strategy_series_for_weights(series_map, {"A": 0.5, "B": 0.0, "C": 0.5})
    assert set(aligned.returns_by_strategy.keys()) == {"A", "C"}
    assert aligned.alignment_method == "inner_join_nonzero_weighted_strategies"


def test_proposed_union_alignment():
    series_map = {
        "A": _series([0.01] * 4),
        "B": _series([0.02] * 4, start="2026-01-02"),
        "C": _series([0.03] * 4, start="2026-01-03"),
    }
    current = {"A": 0.5, "B": 0.5, "C": 0.0}
    proposed = {"A": 0.0, "B": 0.0, "C": 0.5}
    union = {
        strategy_id: max(current.get(strategy_id, 0.0), proposed.get(strategy_id, 0.0))
        for strategy_id in set(current) | set(proposed)
    }
    aligned = align_strategy_series_for_weights(series_map, union)
    assert set(aligned.returns_by_strategy.keys()) == {"A", "B", "C"}
    assert aligned.observations == 2
