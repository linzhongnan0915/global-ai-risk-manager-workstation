from pathlib import Path
import json

import pandas as pd

from src.strategies.frozen_active_signals import ACTIVE_IDS
from src.strategies.shadow_live_operations import (
    ACTIVE_COUNT,
    EQUAL_WEIGHT,
    LEGACY_ACTIVE_COUNT,
    LEGACY_EQUAL_WEIGHT,
    RAW_FORWARD_LABEL,
    _effective_previous_weight,
    _trade_legs,
    update_raw_ohlcv,
)


def test_frozen_active_contract_and_no_accepted_return_fallback():
    source = Path("src/strategies/shadow_live_operations.py").read_text(encoding="utf-8")
    assert len(ACTIVE_IDS) == ACTIVE_COUNT == 17
    assert EQUAL_WEIGHT == 1 / 17
    assert LEGACY_ACTIVE_COUNT == 16
    assert LEGACY_EQUAL_WEIGHT == 1 / 16
    assert '"accepted_series_pnl_fallback": False' in source
    assert RAW_FORWARD_LABEL == "FORWARD_RAW_SHADOW_LIVE"


def test_trade_generation_actions():
    assert _trade_legs(0.0, 0.2) == [("BUY", 0.2)]
    assert _trade_legs(0.2, 0.0) == [("SELL", 0.2)]
    assert _trade_legs(0.0, -0.2) == [("SHORT", 0.2)]
    assert _trade_legs(-0.2, 0.0) == [("COVER", 0.2)]
    assert _trade_legs(-0.2, 0.2) == [("COVER", 0.2), ("BUY", 0.2)]
    assert _trade_legs(0.2, 0.2) == []
    resized = _effective_previous_weight(0.10, 62_500, 1_000_000 / 17)
    assert resized > 0.10
    assert _trade_legs(resized, 0.10)[0][0] == "SELL"


def test_incremental_raw_ohlcv_update(monkeypatch, tmp_path):
    monkeypatch.setattr("src.strategies.shadow_live_operations._entry_eligibility_universe", lambda root: ["AAA"])
    monkeypatch.setattr("src.strategies.shadow_live_operations._operational_pricing_universe", lambda root, entry: ["AAA", "OLD"])
    calls = []

    def fake_download(tickers, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame([
            {"date": "2026-06-11", "ticker": ticker, "provider_symbol": ticker, "open": 10, "high": 11,
             "low": 9, "close": 10, "adj_close": 10, "volume": 1_000_000, "source": "yfinance"}
            for ticker in tickers
        ]), pd.DataFrame()

    monkeypatch.setattr("src.strategies.shadow_live_operations._download_with_single_ticker_fallback", fake_download)
    first, _, audit = update_raw_ohlcv(tmp_path, end_date="2026-06-12")
    second, _, _ = update_raw_ohlcv(tmp_path, end_date="2026-06-12")
    assert len(first) == len(second) == 2
    assert audit["duplicate_date_count"] == 0
    assert audit["entry_eligibility_universe_size"] == 1
    assert audit["operational_pricing_universe_size"] == 2
    assert calls[0]["start_date"] == "2024-01-01"
    assert len(calls) == 1


def test_generated_raw_outputs_reconcile():
    output = Path("output/shadow_live")
    manifest = json.loads((output / "daily_run_manifest.json").read_text(encoding="utf-8"))
    targets = pd.read_csv(output / "target_position_snapshots.csv")
    post = pd.read_csv(output / "post_trade_holdings.csv")
    trades = pd.read_csv(output / "trade_log.csv")
    assert manifest["runner_mode"] == "RAW DATA SIGNAL RUNNER"
    assert manifest["accepted_series_pnl_fallback"] is False
    assert manifest["signal_functions_invoked"] == 17
    assert manifest["successful_strategy_count"] == 17
    assert manifest["failed_strategy_count"] == 0
    assert not targets.empty and not post.empty and not trades.empty
    assert {"simulated_notional", "simulated_quantity", "simulated_execution_price", "realized_pnl", "unrealized_pnl"} <= set(post)
    assert set(targets["record_label"]) == {RAW_FORWARD_LABEL}
    assert not targets.duplicated(["signal_date", "strategy_id", "ticker"]).any()
    assert not trades["trade_id"].duplicated().any()
    assert all(value is True for key, value in manifest["reconciliation"].items() if isinstance(value, bool))


def test_segment_continuity_and_exit_only_contract():
    output = Path("output/shadow_live")
    portfolio = pd.read_csv(output / "portfolio_daily_ledger.csv")
    manifest = json.loads((output / "daily_run_manifest.json").read_text(encoding="utf-8"))
    coverage = pd.read_csv(output / "operational_pricing_coverage.csv")
    diagnosis = pd.read_csv(output / "seed_holding_diagnosis.csv")
    transition = portfolio.loc[portfolio["record_label"].eq("RETROSPECTIVE_PAPER_BACKFILL")].iloc[-1]
    raw = portfolio.loc[portfolio["record_label"].eq(RAW_FORWARD_LABEL)]
    assert transition["ending_nav"] == raw.iloc[0]["beginning_nav"]
    assert not portfolio["date"].duplicated().any()
    assert coverage["entry_eligible"].sum() == 229
    assert len(coverage) == 301
    assert coverage["pricing_status"].eq("PRICED").all()
    assert diagnosis["strategy_id"].nunique() == 6
    assert diagnosis["ticker"].nunique() == 72
    assert manifest["reconciliation"]["exit_only_securities_never_increased"] is True
    assert manifest["reconciliation"]["prior_n16_records_preserved"] is True
    assert manifest["reconciliation"]["effective_n17_weights_equal_1_17"] is True
