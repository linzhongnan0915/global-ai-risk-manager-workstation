import pandas as pd
import pytest
from pathlib import Path

from src.strategies.final_challenge_research import _orthogonalize, fundamental_scores, ohlcv_scores
from src.strategies.fundamental_research import build_raw_component_panel
from src.strategies.platform_registry import CHALLENGE_CANDIDATE_IDS, CHALLENGE_SELECTION_STATUS, EVENT_PANEL_CANDIDATE_IDS
from tests.test_fundamental_research import _context, _facts

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "output/research/final_strict_challenge_batch_v1"


def test_orthogonalized_score_has_negligible_exposure():
    index = pd.date_range("2024-01-01", periods=2)
    columns = [f"T{i:02d}" for i in range(30)]
    exposure = pd.DataFrame([range(30), range(30)], index=index, columns=columns, dtype=float)
    score = exposure * 2 + pd.DataFrame([[(i % 3) for i in range(30)]] * 2, index=index, columns=columns)
    residual = _orthogonalize(score, [exposure])
    assert abs(residual.loc[index[0]].corr(exposure.loc[index[0]])) < 1e-10


def test_challenge_scores_use_prior_information_and_preserve_missing():
    context = _context(days=320, tickers=20)
    scores = ohlcv_scores(context)
    changed = _context(days=320, tickers=20)
    for field in ("open", "high", "low", "close", "adj_close", "volume"):
        changed.panels[field].iloc[-1] *= 10
    changed_scores = ohlcv_scores(changed)
    for strategy_id in scores:
        pd.testing.assert_series_equal(scores[strategy_id].iloc[-1], changed_scores[strategy_id].iloc[-1])
    raw = build_raw_component_panel(_facts(context), context, context.panels["close"].index[::20])
    fundamental = fundamental_scores(raw, context)
    assert len(fundamental) == 8
    assert fundamental["CASH_CONVERSION_IMPROVEMENT"].isna().all().all()


def test_challenge_outputs_and_trade_log_reconcile():
    summary = pd.read_csv(PACK / "candidate_summary.csv").set_index("strategy_id")
    daily = pd.read_csv(PACK / "daily_strategy_returns.csv")
    trades = pd.read_csv(PACK / "trade_log.csv")
    assert set(summary.index) == set(CHALLENGE_CANDIDATE_IDS)
    for strategy_id in CHALLENGE_CANDIDATE_IDS:
        if strategy_id not in {"ORTHOGONAL_LOW_ACCRUAL_MOMENTUM", *EVENT_PANEL_CANDIDATE_IDS}:
            assert summary.loc[strategy_id, "classification"] == CHALLENGE_SELECTION_STATUS[strategy_id]["status"]
        daily_cost = daily.loc[daily["strategy_id"].eq(strategy_id), "transaction_cost"].sum()
        trade_cost = trades.loc[trades["strategy_id"].eq(strategy_id), "estimated_transaction_cost"].sum()
        assert trade_cost == pytest.approx(daily_cost)
        assert summary.loc[strategy_id, "trade_cost_reconciliation_error"] < 1e-12
