import pandas as pd
import pytest
from pathlib import Path

from src.strategies.event_panel_research import event_scores
from src.strategies.fundamental_data import build_filing_event_panel, normalize_company_facts
from src.strategies.platform_registry import EVENT_PANEL_CANDIDATE_IDS, EVENT_PANEL_SELECTION_STATUS
from tests.test_fundamental_point_in_time import _company_facts, _submissions
from tests.test_fundamental_research import _context

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "output/research/event_panel_final_four_strategy_batch_v1"


def test_event_scores_begin_only_after_publication_trade_date():
    context = _context(days=320, tickers=20)
    facts = normalize_company_facts("T00", _company_facts(), _submissions())
    events = build_filing_event_panel(facts, context.panels["close"].index)
    scores = event_scores(events, context)
    for score in scores.values():
        assert score.loc[:pd.Timestamp("2024-02-01"), "T00"].isna().all()


def test_event_panel_outputs_statuses_and_trade_logs_reconcile():
    summary = pd.read_csv(PACK / "candidate_summary.csv").set_index("strategy_id")
    daily = pd.read_csv(PACK / "daily_strategy_returns.csv")
    trades = pd.read_csv(PACK / "trade_log.csv")
    events = pd.read_csv(PACK / "filing_event_panel.csv", parse_dates=["availability_datetime", "first_valid_trading_date"])
    assert set(summary.index) == set(EVENT_PANEL_CANDIDATE_IDS)
    assert (events["first_valid_trading_date"] > events["availability_datetime"].dt.tz_localize(None).dt.normalize()).all()
    for strategy_id in EVENT_PANEL_CANDIDATE_IDS:
        assert summary.loc[strategy_id, "classification"] == EVENT_PANEL_SELECTION_STATUS[strategy_id]["status"]
        daily_cost = daily.loc[daily["strategy_id"].eq(strategy_id), "transaction_cost"].sum()
        trade_cost = trades.loc[trades["strategy_id"].eq(strategy_id), "estimated_transaction_cost"].sum()
        assert trade_cost == pytest.approx(daily_cost)
        assert summary.loc[strategy_id, "trade_cost_reconciliation_error"] < 1e-12
    hedge = summary.loc["HEDGED_RESIDUAL_MOMENTUM_V3"]
    assert abs(hedge["realized_beta"]) <= 0.10
    assert hedge["total_hedge_transaction_cost"] > 0
