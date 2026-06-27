from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.strategies.strategy_factory_data import ensure_data_layout, write_inventory_and_quality
from src.strategies.strategy_factory_us_stock_backtest import _turnover_summary
from src.strategies.strategy_factory_variant_evaluation import REQUIRED_EVALUATION_ARTIFACTS, evaluate_all_variants, evaluate_single_variant, _metric_summary


RUN_ID = "SF_RUN_VARIANT_EVAL_FIXTURE"
VARIANT_ID = "COPPER_CPER_MOMENTUM_21_63_V1"


def test_metric_summary_turnover_is_raw_cumulative_one_way_not_percent_scaled() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-02", periods=4),
            "net_return": [0.01, 0.0, -0.005, 0.002],
            "benchmark_return": [0.0, 0.0, 0.0, 0.0],
            "turnover": [1.0, 0.0, 1.0, 0.0],
            "cost_drag": [0.0005, 0.0, 0.0005, 0.0],
        }
    )

    metrics = _metric_summary(daily, "SPY", 5.0)

    assert metrics["turnover"] == 2.0
    assert metrics["cost_drag"] == 0.001
    assert metrics["turnover"] != 200.0


def test_us_stock_turnover_summary_keeps_nonzero_annualized_value() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-02", periods=252),
            "turnover": [0.0] * 20 + [0.25] + [0.0] * 210 + [0.50] + [0.0] * 20,
        }
    )

    summary = _turnover_summary(daily)

    assert summary["turnover_unit"] == "ANNUALIZED_ONE_WAY_MULTIPLE"
    assert summary["average_rebalance_turnover"] == 0.375
    assert summary["rebalance_frequency_per_year"] == 2.0
    assert summary["annualized_turnover"] == 0.75


def _write_local_proxy_data(data_root: Path, include_benchmark: bool = True) -> None:
    ensure_data_layout(data_root)
    dates = pd.bdate_range("2023-01-02", periods=340)
    rows = []
    symbols = ["CPER", "DBC", "UUP", "COPX", "XME", "SPY"] if include_benchmark else ["CPER"]
    for symbol in symbols:
        for idx, date in enumerate(dates):
            drift = {"CPER": 0.045, "DBC": 0.025, "UUP": -0.005, "COPX": 0.055, "XME": 0.04, "SPY": 0.03}.get(symbol, 0.02)
            seasonal = ((idx % 37) - 18) * 0.015
            price = 20.0 + drift * idx + seasonal
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "open": price,
                    "high": price + 0.3,
                    "low": price - 0.3,
                    "close": price,
                    "adj_close": price,
                    "volume": 1000 + idx,
                }
            )
    prices = pd.DataFrame(rows)
    prices.to_csv(data_root / "prices" / "daily_ohlcv.csv", index=False)
    write_inventory_and_quality(data_root, prices, "TEST_FIXTURE", [] if include_benchmark else ["DBC"])


def _write_local_etf_data(data_root: Path) -> None:
    ensure_data_layout(data_root)
    dates = pd.bdate_range("2022-01-03", periods=360)
    symbols = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
    rows = []
    for sidx, symbol in enumerate(symbols):
        for idx, date in enumerate(dates):
            drift = 0.025 + sidx * 0.004
            wave = ((idx + sidx * 3) % 29) * 0.012
            price = 50.0 + drift * idx + wave
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "open": price,
                    "high": price + 0.2,
                    "low": price - 0.2,
                    "close": price,
                    "adj_close": price,
                    "volume": 100000 + idx,
                }
            )
    prices = pd.DataFrame(rows)
    prices.to_csv(data_root / "prices" / "daily_ohlcv.csv", index=False)
    write_inventory_and_quality(data_root, prices, "TEST_ETF_FIXTURE", [])


def _write_local_us_stock_data(data_root: Path) -> None:
    ensure_data_layout(data_root)
    dates = pd.bdate_range("2021-01-04", periods=420)
    symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO", "SPY"]
    rows = []
    for sidx, symbol in enumerate(symbols):
        for idx, date in enumerate(dates):
            drift = 0.035 + sidx * 0.003
            wave = ((idx + sidx * 5) % 41) * 0.01
            price = 40.0 + drift * idx + wave
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "open": price,
                    "high": price + 0.2,
                    "low": price - 0.2,
                    "close": price,
                    "adj_close": price,
                    "volume": 1000000 + idx,
                }
            )
    prices = pd.DataFrame(rows)
    prices.to_csv(data_root / "prices" / "daily_ohlcv.csv", index=False)
    write_inventory_and_quality(data_root, prices, "TEST_US_STOCK_FIXTURE", [])


def _write_variant_spec(root: Path) -> Path:
    variant_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / VARIANT_ID
    variant_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "schema_version": "strategy_factory_variant_spec_v1",
        "variant_id": VARIANT_ID,
        "variant_name": "CPER Momentum 21/63",
        "source_run_id": RUN_ID,
        "source_material_ids": ["MAT_CONTROLLED_COPPER_FIXTURE"],
        "thesis": "Copper ETF proxy trends may persist over short and medium horizons.",
        "signal_formula": "Long CPER when 21d momentum and 63d momentum are both positive; flat otherwise.",
        "universe_or_proxy": ["CPER"],
        "benchmark": "DBC",
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "features": ["momentum_21d", "momentum_63d", "commodity_basket_proxy_dbc"],
        "model_plan": {"split_method": "chronological_no_shuffle"},
        "data_requirements": ["CPER", "DBC", "daily adjusted OHLCV"],
        "testability_status": "PROXY_ONLY",
        "blocked_reason": None,
        "why_it_may_work": "Trend persistence.",
        "why_it_may_fail": "Whipsaw and broad commodity beta.",
    }
    (variant_dir / "variant_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return variant_dir


def _write_etf_variant_spec(root: Path, variant_id: str = "ETF_ROTATION_63_126_TOP2_V1") -> Path:
    variant_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    variant_dir.mkdir(parents=True, exist_ok=True)
    universe = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
    spec = {
        "schema_version": "strategy_factory_variant_spec_v1",
        "variant_id": variant_id,
        "variant_name": "ETF Momentum Rotation 63/126 Top 2",
        "theme": "etf_momentum_rotation",
        "strategy_name": "ETF Momentum Rotation 63/126 Top 2",
        "source_run_id": RUN_ID,
        "source_material_ids": ["MAT_ETF_FIXTURE"],
        "thesis": "Cross-asset ETF momentum fixture thesis.",
        "signal_formula": "Rank ETFs by 63d plus 126d momentum monthly; hold top 2 equal-weight.",
        "universe_or_proxy": universe,
        "benchmark": "SPY",
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "features": ["momentum_63d", "momentum_126d", "cross_sectional_rank"],
        "model_plan": {"status": "NO_ML_USED"},
        "data_requirements": [*universe, "daily adjusted OHLCV"],
        "testability_status": "READY_TO_TEST",
        "blocked_reason": None,
        "why_it_may_work": "ETF momentum may persist.",
        "why_it_may_fail": "Momentum may reverse.",
    }
    (variant_dir / "variant_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return variant_dir


def _write_us_stock_variant_spec(root: Path, variant_id: str = "US_STOCK_MOMENTUM_12_1_TOP50_V1") -> Path:
    variant_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    variant_dir.mkdir(parents=True, exist_ok=True)
    universe = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO"]
    spec = {
        "schema_version": "strategy_factory_variant_spec_v1",
        "variant_id": variant_id,
        "variant_name": "U.S. Stock Momentum 12-1 Top 50",
        "theme": "us_stock_cross_sectional_momentum_quality",
        "strategy_name": "U.S. Stock Momentum 12-1 Top 50",
        "source_run_id": RUN_ID,
        "source_material_ids": ["MAT_US_STOCK_FIXTURE"],
        "generated_from_material": True,
        "source_material_path": "strategy_factory/intake_queue/examples/us_stock_momentum_quality_material.md",
        "source_material_hash": "fixture_us_stock_material_hash",
        "thesis": "U.S. stock cross-sectional momentum fixture thesis.",
        "signal_formula": "Rank stocks by 252d momentum excluding the most recent 21 trading days; hold top basket equal-weight monthly.",
        "universe_or_proxy": universe,
        "benchmark": "SPY",
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "features": ["momentum_252d_ex_recent_21d", "quality_proxy_missing_evidence"],
        "model_plan": {"status": "NO_ML_USED"},
        "data_requirements": [*universe, "SPY", "U.S. equity daily adjusted OHLCV"],
        "testability_status": "READY_TO_TEST",
        "blocked_reason": None,
        "why_it_may_work": "U.S. stock momentum may persist.",
        "why_it_may_fail": "Momentum may reverse and quality data is missing.",
    }
    (variant_dir / "variant_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return variant_dir


def _write_us_stock_low_vol_variant_spec(root: Path, variant_id: str = "US_STOCK_LOW_VOL_63D_TOP20_V1") -> Path:
    variant_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    variant_dir.mkdir(parents=True, exist_ok=True)
    universe = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO"]
    spec = {
        "schema_version": "strategy_factory_variant_spec_v1",
        "variant_id": variant_id,
        "variant_name": "U.S. Stock Low Vol 63D Top 20",
        "theme": "us_stock_low_vol_defensive",
        "strategy_name": "U.S. Stock Low Vol Defensive 63D Top 20",
        "source_run_id": RUN_ID,
        "source_material_ids": ["MAT_US_LOW_VOL_FIXTURE"],
        "generated_from_material": True,
        "source_material_path": "strategy_factory/intake_queue/examples/us_stock_low_vol_defensive_material.md",
        "source_material_hash": "fixture_us_stock_low_vol_material_hash",
        "thesis": "U.S. stock low-vol defensive fixture thesis.",
        "signal_formula": "Rank stocks by lower 63d realized volatility; hold top defensive basket equal-weight monthly.",
        "universe_or_proxy": universe,
        "benchmark": "SPY",
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "features": ["realized_volatility_63d", "defensive_rank"],
        "model_plan": {"status": "NO_ML_USED"},
        "data_requirements": [*universe, "SPY", "U.S. equity daily adjusted OHLCV"],
        "testability_status": "READY_TO_TEST",
        "blocked_reason": None,
        "why_it_may_work": "Lower realized volatility may reduce drawdown sensitivity.",
        "why_it_may_fail": "Low-vol stocks may lag risk-on rallies.",
    }
    (variant_dir / "variant_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return variant_dir


def _variant_spec(variant_id: str, name: str, universe: list[str], benchmark: str, requirements: list[str], signal: str) -> dict:
    return {
        "schema_version": "strategy_factory_variant_spec_v1",
        "variant_id": variant_id,
        "variant_name": name,
        "source_run_id": RUN_ID,
        "source_material_ids": ["MAT_CONTROLLED_COPPER_FIXTURE"],
        "thesis": "Copper proxy fixture thesis.",
        "signal_formula": signal,
        "universe_or_proxy": universe,
        "benchmark": benchmark,
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "features": ["momentum_21d", "momentum_63d"],
        "model_plan": {"split_method": "chronological_no_shuffle"},
        "data_requirements": requirements,
        "testability_status": "PROXY_ONLY",
        "blocked_reason": None,
        "why_it_may_work": "Fixture trend may persist.",
        "why_it_may_fail": "Fixture may whipsaw.",
    }


def _write_variant_registry(root: Path) -> Path:
    variants_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        _variant_spec("COPPER_CPER_MOMENTUM_21_63_V1", "CPER Momentum 21/63", ["CPER"], "DBC", ["CPER", "DBC"], "Long CPER when 21d and 63d momentum are positive."),
        _variant_spec("COPPER_CPER_UUP_USD_FILTER_V1", "CPER Momentum + UUP/USD Filter", ["CPER"], "DBC", ["CPER", "DBC", "UUP"], "Long CPER when momentum is positive and UUP momentum is non-positive."),
        _variant_spec("COPPER_EQUITY_PROXY_TREND_COPX_XME_V1", "COPX/XME Copper Equity Proxy Trend", ["COPX", "XME"], "SPY", ["COPX", "XME", "SPY"], "Long COPX/XME when both trend and COPX beats SPY."),
    ]
    rows = []
    for spec in specs:
        variant_dir = variants_dir / spec["variant_id"]
        variant_dir.mkdir(parents=True, exist_ok=True)
        spec_path = variant_dir / "variant_spec.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        rows.append(
            {
                "variant_id": spec["variant_id"],
                "variant_name": spec["variant_name"],
                "testability_status": spec["testability_status"],
                "universe_or_proxy": spec["universe_or_proxy"],
                "benchmark": spec["benchmark"],
                "variant_spec_path": str(spec_path),
            }
        )
    registry = {
        "schema_version": "strategy_factory_variant_registry_v1",
        "status": "COMPLETED",
        "source_run_id": RUN_ID,
        "variant_count": len(rows),
        "variants": rows,
    }
    (variants_dir / "variant_registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return variants_dir


def test_gate3a_single_variant_evaluation_creates_real_artifacts(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_proxy_data(data_root)
    variant_dir = _write_variant_spec(workstation_root)
    paper_ledger = workstation_root / "output" / "paper_ledger_fixture.json"
    paper_ledger.parent.mkdir(parents=True, exist_ok=True)
    paper_ledger.write_text('{"ledger": "unchanged"}', encoding="utf-8")
    before_ledger = paper_ledger.read_text(encoding="utf-8")
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = evaluate_single_variant(workstation_root, RUN_ID, VARIANT_ID)

    evaluation_dir = variant_dir / "evaluation"
    assert result["status"] == "COMPLETED"
    assert result["variant_id"] == VARIANT_ID
    for artifact_name in REQUIRED_EVALUATION_ARTIFACTS:
        assert (evaluation_dir / artifact_name).is_file(), artifact_name

    backtest = json.loads((evaluation_dir / "variant_backtest_run.json").read_text(encoding="utf-8"))
    assert backtest["status"] == "COMPLETED"
    assert backtest["universe"] == ["CPER"]
    assert backtest["benchmark"] == "DBC"
    assert backtest["local_data_only"] is True
    assert backtest["paper_ledger"] == "NOT_MUTATED"
    assert backtest["live_trading"] == "NOT_TOUCHED"

    metrics = json.loads((evaluation_dir / "variant_metrics.json").read_text(encoding="utf-8"))
    assert metrics["status"] == "COMPLETED"
    assert isinstance(metrics["sharpe"], float)
    assert isinstance(metrics["annual_return"], float)
    assert metrics["rows"] > 120

    daily = pd.read_csv(evaluation_dir / "variant_daily_returns.csv")
    assert {"net_return", "benchmark_return", "signal_date", "execution_date"}.issubset(daily.columns)
    assert len(daily) == metrics["rows"]

    ml = json.loads((evaluation_dir / "variant_ml_diagnostics_run.json").read_text(encoding="utf-8"))
    assert ml["status"] in {"COMPLETED", "BLOCKED"}
    if ml["status"] == "COMPLETED":
        split = json.loads((evaluation_dir / "variant_train_test_split.json").read_text(encoding="utf-8"))
        assert split["split_method"] == "chronological_no_shuffle"
        assert split["shuffle"] is False
        assert (evaluation_dir / "variant_feature_importance.csv").is_file()
    else:
        assert ml["reason"]

    robustness = json.loads((evaluation_dir / "variant_robustness_run.json").read_text(encoding="utf-8"))
    assert robustness["status"] == "COMPLETED"
    assert robustness["cost_sensitivity"]
    assert robustness["lookback_sensitivity"]

    decision = json.loads((evaluation_dir / "variant_decision.json").read_text(encoding="utf-8"))
    assert decision["recommendation"] in {"Watch", "Modify", "Reject", "Blocked", "Candidate"}
    assert decision["recommendation"] != "Candidate"
    assert paper_ledger.read_text(encoding="utf-8") == before_ledger
    assert "NO_LIVE_TRADING" in result["non_actions"]
    assert "NO_PAPER_LEDGER_MUTATION" in result["non_actions"]


def test_gate3a_single_variant_blocks_without_required_benchmark(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_proxy_data(data_root, include_benchmark=False)
    variant_dir = _write_variant_spec(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = evaluate_single_variant(workstation_root, RUN_ID, VARIANT_ID)

    evaluation_dir = variant_dir / "evaluation"
    assert result["status"] == "BLOCKED"
    metrics = json.loads((evaluation_dir / "variant_metrics.json").read_text(encoding="utf-8"))
    assert metrics["status"] == "BLOCKED"
    assert "sharpe" not in metrics
    ml = json.loads((evaluation_dir / "variant_ml_diagnostics_run.json").read_text(encoding="utf-8"))
    assert ml["status"] == "BLOCKED"
    robustness = json.loads((evaluation_dir / "variant_robustness_run.json").read_text(encoding="utf-8"))
    assert robustness["status"] == "BLOCKED"
    report = (evaluation_dir / "variant_evidence_report.md").read_text(encoding="utf-8")
    assert "Missing required local symbols: DBC" in report


def test_gate3a_etf_variant_uses_etf_backtest_and_missing_ml_truth(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_etf_data(data_root)
    variant_dir = _write_etf_variant_spec(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = evaluate_single_variant(workstation_root, RUN_ID, "ETF_ROTATION_63_126_TOP2_V1")

    evaluation_dir = variant_dir / "evaluation"
    assert result["status"] == "COMPLETED"
    metrics = json.loads((evaluation_dir / "variant_metrics.json").read_text(encoding="utf-8"))
    assert metrics["status"] == "COMPLETED"
    assert metrics["theme"] == "etf_momentum_rotation"
    assert metrics["benchmark"] == "SPY"
    assert metrics["universe"] == ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
    assert isinstance(metrics["sharpe"], float)
    daily = pd.read_csv(evaluation_dir / "variant_daily_returns.csv")
    assert len(daily) == metrics["rows"]
    assert daily["position"].str.contains("GLD|TLT|QQQ|SPY").any()
    ml = json.loads((evaluation_dir / "variant_ml_diagnostics_run.json").read_text(encoding="utf-8"))
    assert ml["status"] == "BLOCKED"
    assert ml["ml_evidence_status"] == "MISSING_EVIDENCE"
    assert "No ML evidence available for ETF Momentum Rotation" in ml["reason"]
    text = (evaluation_dir / "variant_evidence_report.md").read_text(encoding="utf-8")
    assert "ETF Momentum Rotation" in text
    assert "MISSING_EVIDENCE" in text
    assert "COPX" not in text
    assert "XME" not in text
    assert "Copper Equity Proxy Trend" not in text


def test_gate3a_us_stock_variant_uses_stock_backtest_and_missing_quality_ml_truth(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_us_stock_data(data_root)
    variant_dir = _write_us_stock_variant_spec(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = evaluate_single_variant(workstation_root, RUN_ID, "US_STOCK_MOMENTUM_12_1_TOP50_V1")

    evaluation_dir = variant_dir / "evaluation"
    assert result["status"] == "COMPLETED"
    metrics = json.loads((evaluation_dir / "variant_metrics.json").read_text(encoding="utf-8"))
    assert metrics["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert metrics["benchmark"] == "SPY"
    assert metrics["quality_evidence_status"] == "MISSING_EVIDENCE"
    assert "AAPL" in metrics["universe"]
    assert metrics["universe"] != ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
    daily = pd.read_csv(evaluation_dir / "variant_daily_returns.csv")
    assert len(daily) == metrics["rows"]
    assert daily["position"].str.contains("AAPL|MSFT|NVDA").any()
    ml = json.loads((evaluation_dir / "variant_ml_diagnostics_run.json").read_text(encoding="utf-8"))
    assert ml["status"] == "BLOCKED"
    assert ml["ml_evidence_status"] == "MISSING_EVIDENCE"
    assert "No ML evidence available for U.S. Stock Momentum + Quality" in ml["reason"]
    manifest = json.loads((evaluation_dir / "variant_evidence_manifest.json").read_text(encoding="utf-8"))
    readiness = json.loads((evaluation_dir / "variant_readiness_status.json").read_text(encoding="utf-8"))
    assert manifest["generated_from_material"] is True
    assert manifest["source_material_hash"] == "fixture_us_stock_material_hash"
    assert manifest["evidence_status"] == "EVIDENCE_AVAILABLE"
    assert manifest["backtest_status"] == "COMPLETED"
    assert manifest["benchmark"] == "SPY"
    assert manifest["input_universe_path"]
    assert manifest["price_data_source_path"]
    assert manifest["transaction_cost_assumption"] == 5.0
    assert manifest["ml_truth_status"] == "MISSING_EVIDENCE"
    assert manifest["ml_summary"] == "No ML evidence available"
    assert "COPX" not in json.dumps(manifest)
    assert readiness["automation_ready"] is True
    assert readiness["automation_block_reason"] == "BACKTEST_METRICS_AVAILABLE; ML_MISSING_BUT_NOT_BLOCKING"
    summary = json.loads((evaluation_dir / "backtest_summary.json").read_text(encoding="utf-8"))
    signal = json.loads((evaluation_dir / "signal_definition.json").read_text(encoding="utf-8"))
    holdings = pd.read_csv(evaluation_dir / "holdings_by_rebalance.csv")
    perf = pd.read_csv(evaluation_dir / "performance_series.csv")
    assert summary["signal_definition"].startswith("12-1 momentum")
    assert summary["universe_count"] >= 5
    assert summary["data_quality_status"] == "PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE"
    assert signal["formula"] == "price[t-21] / price[t-252] - 1"
    assert "weights.shift(1)" in signal["lookahead_check"]
    assert not holdings.empty
    assert not perf.empty
    text = (evaluation_dir / "variant_evidence_report.md").read_text(encoding="utf-8")
    assert "U.S. Stock Momentum" in text
    assert "MISSING_EVIDENCE" in text
    assert "COPX" not in text
    assert "XME" not in text
    assert "ETF Momentum Rotation" not in text


def test_low_vol_defensive_variant_uses_low_vol_backtest_and_missing_ml_truth(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_us_stock_data(data_root)
    variant_dir = _write_us_stock_low_vol_variant_spec(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = evaluate_single_variant(workstation_root, RUN_ID, "US_STOCK_LOW_VOL_63D_TOP20_V1")

    evaluation_dir = variant_dir / "evaluation"
    assert result["status"] == "COMPLETED"
    metrics = json.loads((evaluation_dir / "variant_metrics.json").read_text(encoding="utf-8"))
    assert metrics["theme"] == "us_stock_low_vol_defensive"
    assert metrics["strategy_evidence_family"] == "LOW_VOL_DEFENSIVE"
    assert "realized volatility" in metrics["feature_definition"].lower()
    assert metrics["turnover_unit"] == "ANNUALIZED_ONE_WAY_MULTIPLE"
    assert metrics["turnover_frequency"] == "monthly_rebalance"
    assert "0.5 * sum(abs(w_t - w_t-1))" in metrics["turnover_definition"]
    assert metrics["average_rebalance_turnover"] is not None
    assert metrics["annualized_turnover"] is not None
    assert metrics["turnover"] == metrics["annualized_turnover"]
    assert metrics["benchmark"] == "SPY"
    assert "AAPL" in metrics["universe"]
    assert isinstance(metrics["sharpe"], float)
    ml = json.loads((evaluation_dir / "variant_ml_diagnostics_run.json").read_text(encoding="utf-8"))
    assert ml["status"] == "BLOCKED"
    assert ml["ml_evidence_status"] == "MISSING_EVIDENCE"
    assert "No ML evidence available for U.S. Stock Low Vol Defensive" in ml["reason"]
    manifest = json.loads((evaluation_dir / "variant_evidence_manifest.json").read_text(encoding="utf-8"))
    readiness = json.loads((evaluation_dir / "variant_readiness_status.json").read_text(encoding="utf-8"))
    assert manifest["source_material_hash"] == "fixture_us_stock_low_vol_material_hash"
    assert manifest["evidence_status"] == "EVIDENCE_AVAILABLE"
    assert manifest["backtest_status"] == "COMPLETED"
    assert manifest["ml_truth_status"] == "MISSING_EVIDENCE"
    assert manifest["metrics"]["turnover_unit"] == "ANNUALIZED_ONE_WAY_MULTIPLE"
    assert manifest["metrics"]["annualized_turnover"] == metrics["annualized_turnover"]
    assert readiness["automation_ready"] is True
    summary = json.loads((evaluation_dir / "backtest_summary.json").read_text(encoding="utf-8"))
    signal = json.loads((evaluation_dir / "signal_definition.json").read_text(encoding="utf-8"))
    assert summary["theme"] == "us_stock_low_vol_defensive"
    assert "Low-vol defensive score" in summary["signal_definition"]
    assert signal["signal_name"] == "U.S. stock low-vol defensive rank"
    text = (evaluation_dir / "variant_evidence_report.md").read_text(encoding="utf-8")
    assert "U.S. Stock Low Vol" in text
    assert "MISSING_EVIDENCE" in text
    assert "COPX" not in text
    assert "XME" not in text
    assert "ETF Momentum Rotation" not in text
    assert "U.S. Stock Momentum + Quality" not in text


def test_phase3c_us_stock_missing_data_blocks_readiness_without_copper_ml(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_proxy_data(data_root)
    variant_dir = _write_us_stock_variant_spec(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))
    monkeypatch.setenv("STRATEGY_FACTORY_DISABLE_YFINANCE_DOWNLOAD", "1")

    result = evaluate_single_variant(workstation_root, RUN_ID, "US_STOCK_MOMENTUM_12_1_TOP50_V1")

    evaluation_dir = variant_dir / "evaluation"
    assert result["status"] == "BLOCKED"
    manifest = json.loads((evaluation_dir / "variant_evidence_manifest.json").read_text(encoding="utf-8"))
    readiness = json.loads((evaluation_dir / "variant_readiness_status.json").read_text(encoding="utf-8"))
    ml = json.loads((evaluation_dir / "variant_ml_diagnostics_run.json").read_text(encoding="utf-8"))
    assert manifest["evidence_status"] == "DATA_MISSING"
    assert manifest["metrics"]["sharpe"] == "Missing Evidence"
    assert manifest["ml_truth_status"] == "MISSING_EVIDENCE"
    assert ml["ml_evidence_status"] == "MISSING_EVIDENCE"
    assert readiness["automation_ready"] is False
    assert readiness["automation_block_reason"] == "DATA_MISSING"
    assert "ridge_regression_numpy" not in json.dumps(manifest)


def test_gate3b_all_variants_in_registry_are_attempted_without_ranking(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_local_proxy_data(data_root)
    variants_dir = _write_variant_registry(workstation_root)
    paper_ledger = workstation_root / "output" / "paper_ledger_fixture.json"
    paper_ledger.parent.mkdir(parents=True, exist_ok=True)
    paper_ledger.write_text('{"ledger": "unchanged"}', encoding="utf-8")
    before_ledger = paper_ledger.read_text(encoding="utf-8")
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = evaluate_all_variants(workstation_root, RUN_ID)

    assert result["status"] == "COMPLETED"
    assert result["variants_attempted"] == 3
    assert result["variants_evaluated"] == 3
    assert "NO_VARIANT_RANKING" in result["non_actions"]
    for row in result["results"]:
        evaluation_dir = variants_dir / row["variant_id"] / "evaluation"
        assert evaluation_dir.is_dir()
        assert (evaluation_dir / "variant_decision.json").is_file()
        assert (evaluation_dir / "variant_metrics.json").is_file()
        assert (evaluation_dir / "variant_ml_diagnostics_run.json").is_file()
        assert (evaluation_dir / "variant_robustness_run.json").is_file()
        metrics = json.loads((evaluation_dir / "variant_metrics.json").read_text(encoding="utf-8"))
        assert metrics.get("status") == "COMPLETED" or metrics.get("reason")
        backtest = json.loads((evaluation_dir / "variant_backtest_run.json").read_text(encoding="utf-8"))
        assert backtest.get("live_trading") == "NOT_TOUCHED"
        assert backtest.get("deploy") in {"NOT_RUN", None}
        assert backtest.get("paper_ledger") == "NOT_MUTATED"
    forbidden = {"ranking.json", "ranked_variants.json", "variant_ranking.json"}
    assert not forbidden.intersection({path.name for path in variants_dir.rglob("*")})
    assert paper_ledger.read_text(encoding="utf-8") == before_ledger
