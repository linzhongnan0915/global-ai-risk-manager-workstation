from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.fundamental_research import (
    CANDIDATE_FORMULAS,
    _raw_components_for_ticker,
    build_candidate_scores,
    build_raw_component_panel,
    build_trade_log,
    normalized_capex,
    run_candidate,
    safe_divide,
)
from src.strategies.strategy_factory import StrategyContext


def _context(days: int = 80, tickers: int = 12) -> StrategyContext:
    dates = pd.bdate_range("2024-01-02", periods=days)
    names = [f"T{index:02d}" for index in range(tickers)]
    base = np.arange(tickers, dtype=float) + 20
    close = pd.DataFrame([base + day * 0.03 for day in range(days)], index=dates, columns=names)
    open_prices = close - 0.10
    volume = pd.DataFrame(2_000_000.0, index=dates, columns=names)
    daily_returns = close.pct_change(fill_method=None)
    return StrategyContext(
        panels={
            "open": open_prices,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "adj_close": close,
            "volume": volume,
        },
        daily_returns=daily_returns,
        market_return=daily_returns.mean(axis=1),
        lagged_beta=pd.DataFrame(1.0, index=dates, columns=names),
        lagged_adv=close.mul(volume).shift(1),
    )


def _facts(context: StrategyContext) -> pd.DataFrame:
    rows = []
    for ticker_index, ticker in enumerate(context.panels["close"].columns):
        for year_index, (end, accepted) in enumerate(
            [
                ("2021-12-31", "2022-02-15T18:00:00Z"),
                ("2022-12-31", "2023-02-15T18:00:00Z"),
                ("2023-12-31", "2024-02-15T18:00:00Z"),
            ]
        ):
            scale = 1 + ticker_index / 20
            values = {
                "revenue": (100 + 15 * year_index) * scale,
                "gross_profit": (40 + 8 * year_index) * scale,
                "operating_income": (15 + 4 * year_index) * scale,
                "net_income": (10 + 3 * year_index) * scale,
                "assets": (200 + 12 * year_index) * scale,
                "equity": (90 + 6 * year_index) * scale,
                "operating_cash_flow": (18 + 5 * year_index) * scale,
                "capex": (6 + year_index) * scale,
                "liabilities": (110 + 3 * year_index) * scale,
                "dividends_paid": (2 + year_index) * scale,
                "share_repurchases": (3 + year_index) * scale,
                "shares_outstanding": 10_000_000 + ticker_index * 100_000,
            }
            for field, value in values.items():
                rows.append(
                    {
                        "ticker": ticker,
                        "field": field,
                        "taxonomy_tag": field,
                        "fiscal_period_end": pd.Timestamp(end).date(),
                        "form": "10-K",
                        "availability_datetime": pd.Timestamp(accepted),
                        "value": value,
                    }
                )
    return pd.DataFrame(rows)


def test_capex_sign_convention_and_safe_denominators():
    assert normalized_capex(-25.0) == 25.0
    assert normalized_capex(25.0) == 25.0
    assert np.isnan(safe_divide(10.0, 0.0))
    assert safe_divide(10.0, -2.0) == pytest.approx(-5.0)


def test_point_in_time_panel_excludes_future_filing_and_uses_prior_close_for_market_cap():
    context = _context(days=40)
    facts = _facts(context)
    dates = context.panels["close"].index
    raw = build_raw_component_panel(facts, context, dates)

    assert raw.loc[(pd.Timestamp("2024-02-15"), "T00"), "annual_revenue_growth"] == pytest.approx(0.15)
    first_available = pd.Timestamp("2024-02-16")
    row = raw.loc[(first_available, "T00")]
    assert row["annual_revenue_growth"] == pytest.approx(15 / 115)
    prior_close = context.panels["close"].shift(1).loc[first_available, "T00"]
    assert row["market_cap"] == pytest.approx(10_000_000 * prior_close)


def test_missing_fundamental_components_remain_missing():
    context = _context(days=40)
    facts = _facts(context)
    facts = facts.loc[~((facts["ticker"] == "T00") & (facts["field"] == "gross_profit"))]
    raw = build_raw_component_panel(facts, context, context.panels["close"].index)

    row = raw.loc[(pd.Timestamp("2024-02-16"), "T00")]
    assert np.isnan(row["quality_gp_assets"])
    assert row["quality_op_assets"] != 0


def test_all_twelve_candidate_scores_and_smoke_backtests_run():
    context = _context()
    facts = _facts(context)
    dates = context.panels["close"].index
    raw = build_raw_component_panel(facts, context, dates)
    scores = build_candidate_scores(raw, dates, context.panels["close"].columns)

    assert set(scores) == set(CANDIDATE_FORMULAS)
    for strategy_id, score in scores.items():
        daily, _, trades, summary = run_candidate(strategy_id, score, context, run_id="TEST_RUN")
        assert not daily.empty
        assert summary["live_allocation_approved"] is False
        assert summary["trade_cost_reconciliation_error"] < 1e-12
        if not trades.empty:
            assert set(trades["record_status"]) == {"SIMULATED | RESEARCH ONLY | NO LIVE FILL"}


def test_new_candidate_components_preserve_missing_values():
    context = _context(days=40)
    facts = _facts(context)
    facts = facts.loc[~((facts["ticker"] == "T00") & (facts["field"] == "share_repurchases"))]
    raw = build_raw_component_panel(facts, context, context.panels["close"].index)
    row = raw.loc[(pd.Timestamp("2024-02-16"), "T00")]

    assert row["revenue_acceleration"] == pytest.approx((15 / 115) - (15 / 100))
    assert row["annual_ocf_growth"] > 0
    assert row["negative_liabilities_assets"] < 0
    assert np.isnan(row["shareholder_yield"])


def test_trade_log_weight_and_cost_reconciliation():
    dates = pd.bdate_range("2024-01-02", periods=3)
    target = pd.DataFrame({"A": [0.5, -0.5, 0.0], "B": [-0.5, 0.5, 0.0]}, index=dates)
    prices = pd.DataFrame({"A": [10.0, 11.0, 12.0], "B": [20.0, 21.0, 22.0]}, index=dates)
    trades = build_trade_log("TEST", target, prices, run_id="TEST_RUN")

    expected_turnover = target.diff().abs().sum(axis=1).fillna(target.abs().sum(axis=1))
    expected_turnover.iloc[0] = target.iloc[0].abs().sum()
    expected_turnover.iloc[-1] = 0.0  # No next open exists for the final signal date.
    by_date = trades.groupby("execution_date")["turnover_contribution"].sum().reindex(
        [day.date().isoformat() for day in dates], fill_value=0.0
    )
    for day, turnover in expected_turnover.items():
        assert by_date.loc[day.date().isoformat()] == pytest.approx(turnover)
    assert trades["estimated_transaction_cost"].sum() == pytest.approx(expected_turnover.sum() * 0.0005)
