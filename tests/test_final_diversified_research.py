import pandas as pd

from src.strategies.final_diversified_research import fundamental_scores, ohlcv_scores
from src.strategies.fundamental_research import build_raw_component_panel
from tests.test_fundamental_research import _context, _facts


def test_diversified_ohlcv_scores_use_prior_information():
    context = _context(days=320, tickers=20)
    scores = ohlcv_scores(context)
    changed = _context(days=320, tickers=20)
    for field in ("open", "high", "low", "close", "adj_close", "volume"):
        changed.panels[field].iloc[-1] *= 10
    changed_scores = ohlcv_scores(changed)
    assert len(scores) == 4
    for strategy_id in scores:
        pd.testing.assert_series_equal(scores[strategy_id].iloc[-1], changed_scores[strategy_id].iloc[-1])


def test_diversified_fundamental_scores_preserve_missing_values():
    context = _context(days=320, tickers=20)
    raw = build_raw_component_panel(_facts(context), context, context.panels["close"].index[::20])
    scores = fundamental_scores(raw, context)
    assert len(scores) == 8
    assert scores["WORKING_CAPITAL_DISCIPLINE"].isna().all().all()
