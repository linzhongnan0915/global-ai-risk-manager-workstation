import pandas as pd

from src.strategies.literature_backtests import run_all_literature_backtests, strategy_prototypes


def test_strategy_prototypes_have_required_research_context():
    prototypes = strategy_prototypes()

    assert len(prototypes) >= 5
    assert all(item.hypothesis for item in prototypes)
    assert all(item.failure_modes for item in prototypes)


def test_literature_backtests_run_on_small_price_panel(tmp_path):
    dates = pd.date_range("2024-01-01", periods=220, freq="B")
    tickers = ["SPY", "QQQ", "IWM", "QUAL", "VLUE", "MTUM", "USMV", "IEF", "TLT", "HYG", "UUP", "DBC", "GLD", "DBMF", "BIL", "VIX"]
    rows = []
    for ti, ticker in enumerate(tickers):
        price = 100.0 + ti
        for i, date in enumerate(dates):
            price *= 1.0 + 0.0002 + ((i + ti) % 7 - 3) * 0.0005
            rows.append({"date": date.date().isoformat(), "ticker": ticker, "adj_close": price})
    path = tmp_path / "prices.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    payload = run_all_literature_backtests(path)

    assert payload["results"]
    assert all("backtest" in item and "walk_forward" in item for item in payload["results"])
    first_series = payload["results"][0]["backtest"]["return_series"]
    assert "gross_returns" in first_series
    assert len(first_series["gross_returns"]) == len(first_series["net_returns"])
