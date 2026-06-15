import pytest

from src.risk.correlation import strategy_correlation_report


def test_strategy_correlation_report_requires_equal_length_window():
    returns = {"A": [0.01, 0.02], "B": [0.01, 0.02, 0.03]}
    with pytest.raises(ValueError, match="common dated window"):
        strategy_correlation_report(returns, {"A": "A", "B": "B"}, 0.75)


def test_strategy_correlation_report_flags_breach():
    returns = {
        "A": [0.01, 0.02, -0.01, 0.03],
        "B": [0.011, 0.021, -0.009, 0.031],
        "C": [-0.02, 0.01, 0.0, 0.015],
    }
    report = strategy_correlation_report(returns, {"A": "A", "B": "B", "C": "C"}, 0.75)

    assert report["summary"]["strategy_count"] == 3
    assert report["summary"]["breach_count"] >= 1
    assert report["summary"]["max_pair"]["left_strategy_id"] == "A"
    assert report["summary"]["max_pair"]["right_strategy_id"] == "B"
    assert report["duplicate_exposure_by_strategy"]["A"]["allocation_blocker"] is True
    assert report["duplicate_exposure_by_strategy"]["B"]["reason_code"] == "duplicate_exposure"
