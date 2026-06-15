import numpy as np
import pandas as pd

from src.replication.clone_model import run_fixed_replication, run_rolling_replication


def test_fixed_replication_recovers_linear_exposure():
    index = pd.date_range("2024-01-01", periods=80, freq="D")
    f1 = np.linspace(-0.01, 0.01, 80)
    f2 = np.sin(np.arange(80) / 5) * 0.005
    factors = pd.DataFrame({"SP500": f1, "BOND": f2}, index=index)
    target = pd.Series(0.0002 + 0.6 * f1 - 0.3 * f2, index=index)

    result = run_fixed_replication(target, factors, "TEST", "Test Strategy")

    assert result.r_squared > 0.99
    assert abs(result.betas["SP500"] - 0.6) < 1e-10
    assert abs(result.betas["BOND"] + 0.3) < 1e-10


def test_rolling_replication_runs_without_future_data():
    index = pd.date_range("2024-01-01", periods=90, freq="D")
    f1 = np.linspace(-0.01, 0.01, 90)
    f2 = np.cos(np.arange(90) / 7) * 0.004
    factors = pd.DataFrame({"SP500": f1, "BOND": f2}, index=index)
    target = pd.Series(0.0001 + 0.4 * f1 + 0.2 * f2, index=index)

    result = run_rolling_replication(target, factors, "TEST", "Test Strategy", window=30)

    assert result.method == "rolling_30_day_no_lookahead"
    assert result.observations == 60
    assert result.r_squared > 0.95
