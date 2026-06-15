import pandas as pd

from src.portfolio.return_alignment import align_strategy_series, weighted_portfolio_series


def test_align_strategy_series_uses_inner_join_not_tail_slice():
    series = {
        "A": pd.Series([0.01, 0.02, 0.03], index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])),
        "B": pd.Series([0.04, 0.05], index=pd.to_datetime(["2020-01-02", "2020-01-03"])),
    }
    aligned = align_strategy_series(series, ["A", "B"])

    assert aligned.observations == 2
    assert aligned.start_date == "2020-01-02"
    assert aligned.end_date == "2020-01-03"
    assert aligned.returns_by_strategy["A"] == [0.02, 0.03]
    assert aligned.returns_by_strategy["B"] == [0.04, 0.05]


def test_weighted_portfolio_series_matches_manual_calculation():
    aligned = align_strategy_series(
        {
            "A": pd.Series([0.01, 0.02], index=pd.to_datetime(["2020-01-01", "2020-01-02"])),
            "B": pd.Series([0.03, 0.04], index=pd.to_datetime(["2020-01-01", "2020-01-02"])),
        },
        ["A", "B"],
    )
    portfolio = weighted_portfolio_series(aligned, {"A": 0.6, "B": 0.4})

    assert portfolio["returns"] == [0.01 * 0.6 + 0.03 * 0.4, 0.02 * 0.6 + 0.04 * 0.4]
    assert portfolio["dates"] == ["2020-01-01", "2020-01-02"]


def test_slice_aligned_window_keeps_observations_on_or_after_start_date():
    from src.portfolio.return_alignment import slice_aligned_window, slice_portfolio_series

    aligned = align_strategy_series(
        {
            "A": pd.Series([0.01, 0.02, 0.03], index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])),
            "B": pd.Series([0.04, 0.05, 0.06], index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])),
        },
        ["A", "B"],
    )
    sliced = slice_aligned_window(aligned, "2020-01-02")

    assert sliced.observations == 2
    assert sliced.start_date == "2020-01-02"
    assert sliced.returns_by_strategy["A"] == [0.02, 0.03]

    portfolio = weighted_portfolio_series(aligned, {"A": 1.0, "B": 0.0})
    live = slice_portfolio_series(portfolio, "2020-01-02")
    assert live["dates"] == ["2020-01-02", "2020-01-03"]
    assert len(live["cumulative_return"]) == 2
