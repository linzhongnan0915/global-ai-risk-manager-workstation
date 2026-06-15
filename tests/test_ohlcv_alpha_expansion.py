from __future__ import annotations

import pandas as pd

from src.strategies.ohlcv_alpha_expansion import individual_scores
from tests.test_fundamental_research import _context


def test_ohlcv_alpha_scores_use_prior_information_and_preserve_shape():
    context = _context(days=320, tickers=20)
    scores = individual_scores(context)
    assert len(scores) == 10
    assert all(score.shape == context.panels["close"].shape for score in scores.values())
    changed = _context(days=320, tickers=20)
    for field in ("open", "high", "low", "close", "adj_close", "volume"):
        changed.panels[field].iloc[-1] *= 10
    changed_scores = individual_scores(changed)
    for strategy_id in scores:
        pd.testing.assert_series_equal(scores[strategy_id].iloc[-1], changed_scores[strategy_id].iloc[-1])
