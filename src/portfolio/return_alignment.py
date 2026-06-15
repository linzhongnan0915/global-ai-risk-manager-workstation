"""Align strategy return series on actual calendar dates for portfolio analytics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class AlignedReturnWindow:
    """Common inner-join return window shared by portfolio analytics."""

    dates: list[str]
    returns_by_strategy: dict[str, list[float]]
    start_date: str | None
    end_date: str | None
    observations: int
    alignment_method: str = "inner_join_on_calendar_dates"

    def as_dict(self) -> dict[str, list[float]]:
        return dict(self.returns_by_strategy)


def _empty_window() -> AlignedReturnWindow:
    return AlignedReturnWindow(
        dates=[],
        returns_by_strategy={},
        start_date=None,
        end_date=None,
        observations=0,
    )


def series_map_from_literature_results(results: Iterable[dict]) -> dict[str, pd.Series]:
    """Build dated net-return series keyed by strategy_id."""

    output: dict[str, pd.Series] = {}
    for item in results:
        backtest = item["backtest"]
        series = backtest.get("return_series", {})
        dates = series.get("dates", [])
        values = series.get("net_returns", [])
        if not dates or not values:
            continue
        output[backtest["strategy_id"]] = pd.Series(
            [float(value) for value in values],
            index=pd.to_datetime(dates),
            dtype=float,
            name=backtest["strategy_id"],
        )
    return output


def align_strategy_series(
    series_by_id: dict[str, pd.Series],
    strategy_ids: Iterable[str] | None = None,
) -> AlignedReturnWindow:
    """Inner-join strategy returns on actual dates without fillna or tail slicing."""

    ids = list(strategy_ids) if strategy_ids is not None else sorted(series_by_id)
    usable = [strategy_id for strategy_id in ids if strategy_id in series_by_id]
    if not usable:
        return _empty_window()

    frame = pd.concat({strategy_id: series_by_id[strategy_id] for strategy_id in usable}, axis=1)
    frame = frame.sort_index().dropna(how="any")
    if frame.empty:
        return _empty_window()

    dates = [idx.date().isoformat() for idx in frame.index]
    returns = {
        strategy_id: [float(value) for value in frame[strategy_id]]
        for strategy_id in frame.columns
    }
    return AlignedReturnWindow(
        dates=dates,
        returns_by_strategy=returns,
        start_date=dates[0],
        end_date=dates[-1],
        observations=len(dates),
    )


def align_strategy_series_for_weights(
    series_by_id: dict[str, pd.Series],
    weights: dict[str, float],
    *,
    include_research_universe: bool = False,
) -> AlignedReturnWindow:
    """Inner-join only strategies with non-zero weight in the supplied map.

    For current/proposed comparison, pass the union of non-zero current and proposed IDs.
    """

    if include_research_universe:
        ids = sorted(series_by_id.keys())
    else:
        ids = sorted(strategy_id for strategy_id, weight in weights.items() if float(weight) > 0)
    aligned = align_strategy_series(series_by_id, ids)
    if not aligned.observations:
        return aligned
    return AlignedReturnWindow(
        dates=aligned.dates,
        returns_by_strategy=aligned.returns_by_strategy,
        start_date=aligned.start_date,
        end_date=aligned.end_date,
        observations=aligned.observations,
        alignment_method="inner_join_nonzero_weighted_strategies",
    )


def weighted_portfolio_series(
    aligned: AlignedReturnWindow,
    weights: dict[str, float],
) -> dict[str, list[float]]:
    """Build weighted portfolio return, cumulative return, and drawdown on aligned dates."""

    if not aligned.observations:
        return {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []}

    weighted = []
    for index in range(aligned.observations):
        daily = 0.0
        for strategy_id, series in aligned.returns_by_strategy.items():
            daily += float(weights.get(strategy_id, 0.0)) * float(series[index])
        weighted.append(daily)

    wealth = pd.Series(1.0 + pd.Series(weighted)).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return {
        "dates": list(aligned.dates),
        "returns": [float(value) for value in weighted],
        "cumulative_return": [float(value - 1.0) for value in wealth],
        "drawdown": [float(value) for value in drawdown],
    }


def slice_aligned_window(aligned: AlignedReturnWindow, start_date: str) -> AlignedReturnWindow:
    """Keep observations on or after start_date (ISO calendar date)."""

    if not aligned.observations:
        return _empty_window()
    keep = [index for index, day in enumerate(aligned.dates) if day >= start_date]
    if not keep:
        return _empty_window()
    dates = [aligned.dates[index] for index in keep]
    returns = {
        strategy_id: [series[index] for index in keep]
        for strategy_id, series in aligned.returns_by_strategy.items()
    }
    return AlignedReturnWindow(
        dates=dates,
        returns_by_strategy=returns,
        start_date=dates[0],
        end_date=dates[-1],
        observations=len(dates),
        alignment_method=aligned.alignment_method,
    )


def slice_portfolio_series(series: dict[str, list[float]], start_date: str) -> dict[str, list[float]]:
    """Slice a portfolio series dict to dates on or after start_date."""

    dates = series.get("dates", [])
    if not dates:
        return {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []}
    keep = [index for index, day in enumerate(dates) if day >= start_date]
    if not keep:
        return {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []}

    def _pick(key: str) -> list[float]:
        values = series.get(key, [])
        return [float(values[index]) for index in keep if index < len(values)]

    sliced_returns = _pick("returns")
    if not sliced_returns:
        return {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []}
    wealth = pd.Series(1.0 + pd.Series(sliced_returns)).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return {
        "dates": [dates[index] for index in keep],
        "returns": sliced_returns,
        "cumulative_return": [float(value - 1.0) for value in wealth],
        "drawdown": [float(value) for value in drawdown],
    }
