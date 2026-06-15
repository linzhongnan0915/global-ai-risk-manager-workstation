import math
from statistics import mean, stdev

from src.risk.performance import max_drawdown, sharpe_ratio


def test_sharpe_calculation():
    returns = [0.01, 0.02, -0.01, 0.015]
    expected = mean(returns) / stdev(returns) * math.sqrt(252)

    assert sharpe_ratio(returns) == expected


def test_drawdown_calculation():
    returns = [0.10, -0.10, -0.10, 0.05]

    assert round(max_drawdown(returns), 4) == -0.19

