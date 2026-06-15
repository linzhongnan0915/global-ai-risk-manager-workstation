"""Direction tests for selected C3A1 signals."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.c3a1_signals import low_tail_loss
from src.strategies.strategy_factory import StrategyContext


def _context() -> StrategyContext:
    dates = pd.bdate_range("2024-01-02", periods=140)
    columns = ["GOOD", "BAD"]
    returns = pd.DataFrame(
        {
            "GOOD": np.r_[np.full(130, -0.001), np.full(10, -0.20)],
            "BAD": np.r_[np.full(130, -0.001), np.full(10, -0.35)],
        },
        index=dates,
    )
    close = (1 + returns).cumprod() * 20
    panels = {
        "close": close,
        "adj_close": close.copy(),
        "open": close.copy(),
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": close * 0 + 1_000_000,
    }
    return StrategyContext(
        panels,
        returns,
        returns.mean(axis=1),
        close * 0 + 1.0,
        close * 0 + 20_000_000,
    )


def test_low_tail_loss_ranks_smaller_tail_losses_higher():
    context = _context()
    score = low_tail_loss(context).iloc[-1]
    assert score["GOOD"] > score["BAD"]
