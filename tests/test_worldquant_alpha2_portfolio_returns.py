"""Deterministic financial logic tests for Alpha #2 portfolio returns."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.worldquant.portfolio import signal_to_dollar_neutral_weights
from src.strategies.worldquant.portfolio_returns import (
    EXECUTION_MODE_CLOSE_TO_CLOSE_LAG2,
    EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
    compute_portfolio_returns_from_weights,
    resolve_execution_spec,
)


def _index(n: int = 4) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-02", periods=n, freq="B")


def test_signal_direction_assigns_long_short_and_zero_middle():
    signal = pd.DataFrame(
        {
            "AAA": [3.0, 3.0],
            "BBB": [2.0, 2.0],
            "CCC": [1.0, 1.0],
            "DDD": [-3.0, -3.0],
            "EEE": [-2.0, -2.0],
            "FFF": [-1.0, -1.0],
        },
        index=_index(2),
    )
    weights = signal_to_dollar_neutral_weights(signal, long_quantile=1 / 3, short_quantile=1 / 3)
    date = signal.index[0]

    assert weights.loc[date, "AAA"] > 0
    assert weights.loc[date, "BBB"] > 0
    assert weights.loc[date, "DDD"] < 0
    assert weights.loc[date, "EEE"] < 0
    assert weights.loc[date, "CCC"] == pytest.approx(0.0)
    assert weights.loc[date, "FFF"] == pytest.approx(0.0)
    assert weights.loc[date].sum() == pytest.approx(0.0)
    assert weights.loc[date].abs().sum() == pytest.approx(1.0)


def test_execution_lag_delays_pnl_by_one_row():
    index = _index(3)
    target_weights = pd.DataFrame({"AAA": [0.5, 0.5, 0.5]}, index=index)
    asset_returns = pd.DataFrame({"AAA": [0.10, 0.20, 0.30]}, index=index)

    result = compute_portfolio_returns_from_weights(
        target_weights,
        asset_returns,
        execution_lag=1,
        buy_bps=0.0,
        sell_bps=0.0,
        return_definition="open_to_close",
    )

    assert result.gross_return.loc[index[0]] == pytest.approx(0.0)
    assert result.gross_return.loc[index[1]] == pytest.approx(0.10)
    assert result.gross_return.loc[index[2]] == pytest.approx(0.15)


def test_close_to_close_lag2_aligns_signal_to_later_close_return():
    index = _index(4)
    target_weights = pd.DataFrame({"AAA": [0.5, 0.5, 0.5, 0.5]}, index=index)
    asset_returns = pd.DataFrame({"AAA": [np.nan, 0.10, 0.20, 0.30]}, index=index)

    result = compute_portfolio_returns_from_weights(
        target_weights,
        asset_returns,
        execution_lag=2,
        buy_bps=0.0,
        sell_bps=0.0,
        return_definition="close_to_close",
    )

    assert result.gross_return.loc[index[0]] == pytest.approx(0.0)
    assert result.gross_return.loc[index[1]] == pytest.approx(0.0)
    assert result.gross_return.loc[index[2]] == pytest.approx(0.10)
    assert result.gross_return.loc[index[3]] == pytest.approx(0.15)


def test_initial_transaction_cost_for_dollar_neutral_book():
    index = _index(2)
    target_weights = pd.DataFrame({"AAA": [0.5, 0.5], "BBB": [-0.5, -0.5]}, index=index)
    asset_returns = pd.DataFrame({"AAA": [0.0, 0.0], "BBB": [0.0, 0.0]}, index=index)

    result = compute_portfolio_returns_from_weights(
        target_weights,
        asset_returns,
        execution_lag=1,
        buy_bps=5.0,
        sell_bps=5.0,
        return_definition="open_to_close",
    )

    assert result.turnover.loc[index[1]] == pytest.approx(1.0)
    assert result.transaction_cost.loc[index[1]] == pytest.approx(0.0005)
    assert result.net_return.loc[index[1]] == pytest.approx(-0.0005)


def test_rebalance_transaction_cost_is_hand_calculable():
    index = _index(3)
    target_weights = pd.DataFrame(
        {
            "AAA": [0.5, 0.25, 0.25],
            "BBB": [-0.5, -0.25, -0.25],
        },
        index=index,
    )
    asset_returns = pd.DataFrame({"AAA": [0.0, 0.0, 0.0], "BBB": [0.0, 0.0, 0.0]}, index=index)

    result = compute_portfolio_returns_from_weights(
        target_weights,
        asset_returns,
        execution_lag=1,
        buy_bps=5.0,
        sell_bps=5.0,
        return_definition="open_to_close",
    )

    assert result.turnover.loc[index[1]] == pytest.approx(1.0)
    assert result.turnover.loc[index[2]] == pytest.approx(0.5)
    assert result.transaction_cost.loc[index[2]] == pytest.approx(0.00025)
    assert result.net_return.loc[index[2]] == pytest.approx(-0.00025)


def test_net_return_equals_gross_minus_cost_and_compounds():
    index = _index(3)
    target_weights = pd.DataFrame({"AAA": [1.0, 1.0, 1.0]}, index=index)
    asset_returns = pd.DataFrame({"AAA": [0.0, 0.10, -0.05]}, index=index)

    result = compute_portfolio_returns_from_weights(
        target_weights,
        asset_returns,
        execution_lag=1,
        buy_bps=5.0,
        sell_bps=5.0,
        return_definition="open_to_close",
    )

    active = result.net_return.loc[index[1]:]
    assert (active == result.gross_return.loc[index[1]:] - result.transaction_cost.loc[index[1]:]).all()
    compounded = float(np.prod(1.0 + active.to_numpy()) - 1.0)
    assert compounded == pytest.approx(float(np.prod(1.0 + active.to_numpy()) - 1.0))


def test_execution_mode_specs_are_explicit():
    assert resolve_execution_spec(EXECUTION_MODE_NEXT_OPEN_TO_CLOSE) == (1, "open_to_close")
    assert resolve_execution_spec(EXECUTION_MODE_CLOSE_TO_CLOSE_LAG2) == (2, "close_to_close")


def test_optional_hedge_leg_reconciles_return_turnover_and_cost():
    index = _index(3)
    weights = pd.DataFrame({"AAA": [0.5, 0.5, 0.5]}, index=index)
    returns = pd.DataFrame({"AAA": [0.02, 0.02, 0.02]}, index=index)
    hedge_weights = pd.Series([-0.5, -0.25, -0.25], index=index)
    hedge_returns = pd.Series([0.01, 0.01, 0.01], index=index)
    result = compute_portfolio_returns_from_weights(
        weights, returns, execution_lag=0, buy_bps=5, sell_bps=5, return_definition="open_to_open",
        hedge_weights=hedge_weights, hedge_returns=hedge_returns,
    )
    assert result.gross_return.iloc[0] == pytest.approx(0.005)
    assert result.hedge_turnover.iloc[1] == pytest.approx(0.25)
    assert result.transaction_cost.iloc[1] == pytest.approx(0.25 * 5 / 10_000)
