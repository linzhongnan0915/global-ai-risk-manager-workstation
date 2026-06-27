from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.strategies.strategy_factory_data import (
    DECISION_BLOCKED,
    DECISION_PROXY_ONLY,
    DECISION_READY,
    LocalCsvMarketDataProvider,
    LocalParquetDataProvider,
    evaluate_availability,
    ensure_data_layout,
    infer_data_requirements,
    write_inventory_and_quality,
)
from src.strategies.strategy_factory_plugin import base_state
from src.strategies.strategy_factory_runner import run_current_backtest_ml, run_full_current_run_job


def _fixture_prices(days: int = 130, symbols: tuple[str, ...] = ("CPER", "DBC")) -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-03", periods=days)
    rows = []
    for symbol in symbols:
        base = 20.0 if symbol == "CPER" else 25.0
        drift = 0.04 if symbol == "CPER" else 0.02
        for idx, date in enumerate(dates):
            close = base + idx * drift + (idx % 7) * 0.03
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "open": close - 0.05,
                    "high": close + 0.10,
                    "low": close - 0.10,
                    "close": close,
                    "adj_close": close,
                    "volume": 1000000 + idx,
                }
            )
    return pd.DataFrame(rows)


def _write_csv_fixture(root: Path, prices: pd.DataFrame) -> None:
    ensure_data_layout(root)
    prices.to_csv(root / "prices" / "daily_ohlcv.csv", index=False)
    write_inventory_and_quality(root, prices, "TEST_FIXTURE", [])


def _write_parquet_fixture(root: Path, prices: pd.DataFrame) -> None:
    ensure_data_layout(root)
    prices.to_parquet(root / "prices" / "daily_ohlcv.parquet", index=False)
    returns = prices.sort_values(["symbol", "date"]).copy()
    returns["return"] = returns.groupby("symbol")["adj_close"].pct_change(fill_method=None)
    returns[["date", "symbol", "return"]].dropna().to_parquet(root / "prices" / "daily_returns.parquet", index=False)
    write_inventory_and_quality(root, prices, "TEST_FIXTURE", [])


def _write_current_run(root: Path, text: str = "Copper commodity proxy momentum test spec.") -> Path:
    run_dir = root / "output" / "strategy_factory" / "runs" / "run_fixture"
    run_dir.mkdir(parents=True)
    test_spec = run_dir / "test_spec.md"
    test_spec.write_text(text, encoding="utf-8")
    candidate_path = run_dir / "current_run_candidate.json"
    manifest = {
        "run_id": "run_fixture",
        "batch_id": "batch_fixture",
        "selected_material_ids": ["mat1"],
        "selected_material_names": ["copper_note.md"],
        "candidate_output": {"strategy_id": "CURRENT_RUN_COPPER_FIXTURE"},
        "generated_artifacts": {"test_specs": [str(test_spec)], "current_run_candidate": str(candidate_path)},
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    candidate = {
        "strategy_id": "CURRENT_RUN_COPPER_FIXTURE",
        "name": "Current Run Copper Fixture",
        "current_run": {"current_run_id": "run_fixture", "run_manifest_path": str(manifest_path)},
        "source_evidence": {"run_id": "run_fixture", "artifact_chain": {}},
        "completed_stages": ["TEST_SPEC_CREATED"],
    }
    candidate_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    state_path = root / "output" / "strategy_factory" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "latest_run": {"run_id": "run_fixture", "run_manifest_path": str(manifest_path)},
                "scoped_run_candidates": [candidate],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_local_csv_provider_loads_fixture_data(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    prices = _fixture_prices()
    _write_csv_fixture(data_root, prices)

    loaded = LocalCsvMarketDataProvider(data_root).get_price_history(["CPER"], "2022-01-03", "2022-02-01")

    assert set(loaded["symbol"]) == {"CPER"}
    assert len(loaded) > 10
    assert loaded["close"].notna().all()


def test_local_parquet_provider_loads_fixture_data(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    prices = _fixture_prices()
    _write_parquet_fixture(data_root, prices)

    loaded = LocalParquetDataProvider(data_root).get_price_history(["DBC"], "2022-01-03", "2022-02-01")

    assert set(loaded["symbol"]) == {"DBC"}
    assert len(loaded) > 10
    assert loaded["adj_close"].notna().all()


def test_proxy_data_cache_contains_spy_and_one_copper_proxy(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    prices = _fixture_prices(symbols=("CPER", "SPY", "DBC"))
    _write_parquet_fixture(data_root, prices)

    cached = pd.read_parquet(data_root / "prices" / "daily_ohlcv.parquet")
    symbols = set(cached["symbol"])

    assert "SPY" in symbols
    assert symbols.intersection({"CPER", "JJC", "DBB", "COPX", "XME"})
    assert (data_root / "prices" / "daily_returns.parquet").is_file()


def test_quality_report_preserves_explicit_empty_missing_symbols(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    prices = _fixture_prices(symbols=("CPER", "SPY", "DBC"))
    _write_parquet_fixture(data_root, prices)

    quality = json.loads((data_root / "manifests" / "data_quality_report.json").read_text(encoding="utf-8"))

    assert quality["missing_symbols"] == []


def test_parquet_provider_returns_price_history_and_returns(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    prices = _fixture_prices(symbols=("CPER", "SPY", "DBC"))
    _write_parquet_fixture(data_root, prices)
    provider = LocalParquetDataProvider(data_root)

    price_history = provider.get_price_history(["CPER", "SPY"], "2022-01-03", "2022-03-31")
    returns = provider.get_returns(["CPER", "SPY"], "2022-01-03", "2022-03-31")

    assert sorted(price_history["symbol"].unique()) == ["CPER", "SPY"]
    assert sorted(returns["symbol"].unique()) == ["CPER", "SPY"]
    assert len(returns) > 20
    assert returns["return"].notna().all()


def test_data_availability_ready_when_required_symbols_exist(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(symbols=("CPER", "DBC")))
    provider = LocalCsvMarketDataProvider(data_root)

    availability = evaluate_availability(
        provider,
        {"symbols": ["CPER"], "proxy_groups": [], "benchmark_groups": ["commodities_benchmark"], "benchmark_symbol": "DBC"},
    )

    assert availability.decision == DECISION_READY
    assert availability.usable_symbols == ["CPER"]


def test_data_availability_proxy_only_when_only_proxy_mapping_exists(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(symbols=("CPER", "DBC")))
    provider = LocalCsvMarketDataProvider(data_root)

    availability = evaluate_availability(
        provider,
        {"symbols": ["HG=F"], "proxy_groups": ["copper"], "benchmark_groups": ["commodities_benchmark"], "benchmark_symbol": "DBC"},
    )

    assert availability.decision == DECISION_PROXY_ONLY
    assert "CPER" in availability.usable_symbols
    assert "HG=F" in availability.missing_symbols


def test_data_availability_blocked_when_no_usable_symbols_exist(tmp_path: Path) -> None:
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(symbols=("SPY",)))
    provider = LocalCsvMarketDataProvider(data_root)

    availability = evaluate_availability(
        provider,
        {"symbols": ["HG=F"], "proxy_groups": ["copper"], "benchmark_groups": ["commodities_benchmark"], "benchmark_symbol": "DBC"},
    )

    assert availability.decision == DECISION_BLOCKED
    assert availability.usable_symbols == []


def test_strategy_factory_theme_detection_copper_etf_and_unknown() -> None:
    copper = infer_data_requirements({"run_id": "copper"}, "Copper CPER proxy trend with DBC benchmark")
    etf = infer_data_requirements({"run_id": "etf"}, "ETF momentum rotation using SPY QQQ IWM EFA EEM TLT GLD top 2 monthly")
    unknown = infer_data_requirements({"run_id": "unknown"}, "Natural language idea with no tradable universe")
    us_stock = infer_data_requirements({"run_id": "us"}, "U.S. stock cross-sectional momentum quality screen over a U.S. equity universe")

    assert copper["theme"] == "commodity_proxy_trend"
    assert etf["theme"] == "etf_momentum_rotation"
    assert etf["symbols"] == ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
    assert etf["benchmark_symbol"] == "SPY"
    assert unknown["theme"] == "unknown_review_required"
    assert unknown["benchmark_symbol"] is None
    assert us_stock["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert us_stock["asset_class"] == "us_equity"
    assert us_stock["benchmark_symbol"] == "SPY"


def test_strategy_factory_runner_blocks_without_data_and_does_not_fake_metrics(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    ensure_data_layout(data_root)
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)

    assert result["status"] == "BLOCKED"
    metrics = json.loads(Path(result["artifacts"]["metrics"]).read_text(encoding="utf-8"))
    assert metrics["metrics_available"] is False
    assert "sharpe" not in metrics
    decision = json.loads(Path(result["artifacts"]["testability_decision"]).read_text(encoding="utf-8"))
    assert decision["decision"] == DECISION_BLOCKED


def test_strategy_factory_runner_runs_small_copper_proxy_fixture(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices())
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)

    assert result["status"] == "COMPLETED"
    assert result["backtest"]["testability_decision"] == DECISION_PROXY_ONLY
    metrics = json.loads(Path(result["artifacts"]["metrics"]).read_text(encoding="utf-8"))
    assert metrics["status"] == "COMPLETED"
    assert isinstance(metrics["annual_return"], float)
    assert isinstance(metrics["sharpe"], float)
    daily = pd.read_csv(result["artifacts"]["daily_returns"])
    assert len(daily) > 20
    assert daily["net_return"].notna().all()
    assert Path(result["artifacts"]["equity_curve_svg"]).is_file()
    assert Path(result["artifacts"]["drawdown_svg"]).is_file()
    assert pd.read_csv(result["artifacts"]["equity_curve"]).shape[0] > 20


def test_ml_runner_creates_current_run_diagnostics_and_evidence_report(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(days=260))
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)
    artifacts = result["artifacts"]

    assert result["status"] == "COMPLETED"
    assert result["ml_diagnostics"]["status"] == "COMPLETED"
    assert result["ml_diagnostics"]["model"] == "ridge_regression_numpy"
    assert result["ml_diagnostics"]["features_used"]
    assert result["ml_diagnostics"]["recommendation"] in {"Candidate", "Watch", "Modify", "Reject"}
    for key in (
        "ml_diagnostics_run",
        "feature_importance_csv",
        "feature_importance_json",
        "prediction_quality",
        "train_test_split",
        "leakage_check",
        "evidence_report",
        "intelligence_plan",
        "strategy_type_classification",
        "feature_plan",
        "model_plan",
        "robustness_plan",
        "robustness_run",
        "lookback_sensitivity_csv",
        "lookback_sensitivity_json",
        "cost_sensitivity_csv",
        "cost_sensitivity_json",
        "rebalance_sensitivity_csv",
        "rebalance_sensitivity_json",
        "benchmark_comparison_csv",
        "benchmark_comparison_json",
        "stress_period_summary",
        "ml_lift_vs_rule_signal",
        "robustness_report",
        "validation_scorecard",
        "decision_scorecard",
        "intelligence_report",
    ):
        assert Path(artifacts[key]).is_file(), key
    feature_importance = json.loads(Path(artifacts["feature_importance_json"]).read_text(encoding="utf-8"))
    assert feature_importance["status"] == "COMPLETED"
    assert feature_importance["feature_importance"]
    prediction_quality = json.loads(Path(artifacts["prediction_quality"]).read_text(encoding="utf-8"))
    assert prediction_quality["status"] == "COMPLETED"
    split = json.loads(Path(artifacts["train_test_split"]).read_text(encoding="utf-8"))
    assert split["split_method"] == "chronological_no_shuffle"
    leakage = json.loads(Path(artifacts["leakage_check"]).read_text(encoding="utf-8"))
    assert leakage["status"] == "PASS"
    report = Path(artifacts["evidence_report"]).read_text(encoding="utf-8")
    assert "## Backtest Methodology" in report
    assert "## ML Diagnostics" in report
    assert "## Feature Importance" in report
    assert "## Recommendation" in report


def test_intelligence_layer_creates_copper_artifacts_and_scorecards(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(days=260, symbols=("CPER", "DBC", "UUP", "SPY")))
    _write_current_run(workstation_root, text="Copper commodity macro trend proxy test spec using DBC benchmark and USD risk proxy.")
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)
    artifacts = result["artifacts"]

    for key in (
        "intelligence_plan",
        "strategy_type_classification",
        "feature_plan",
        "model_plan",
        "robustness_plan",
        "robustness_run",
        "lookback_sensitivity_csv",
        "lookback_sensitivity_json",
        "cost_sensitivity_csv",
        "cost_sensitivity_json",
        "rebalance_sensitivity_csv",
        "rebalance_sensitivity_json",
        "benchmark_comparison_csv",
        "benchmark_comparison_json",
        "stress_period_summary",
        "ml_lift_vs_rule_signal",
        "robustness_report",
        "validation_scorecard",
        "decision_scorecard",
        "intelligence_report",
    ):
        assert Path(artifacts[key]).is_file(), key

    classification = json.loads(Path(artifacts["strategy_type_classification"]).read_text(encoding="utf-8"))
    assert classification["strategy_type"] == "commodity trend / macro proxy"

    feature_plan = json.loads(Path(artifacts["feature_plan"]).read_text(encoding="utf-8"))
    feature_names = {row["feature"]: row for row in feature_plan["features"]}
    assert feature_names["momentum_21d"]["status"] == "INCLUDED"
    assert feature_names["momentum_63d"]["status"] == "INCLUDED"
    assert feature_names["momentum_126d"]["status"] == "PLANNED"
    assert feature_names["usd_proxy_uup"]["status"] == "INCLUDED"
    assert feature_names["commodity_basket_proxy_dbc"]["status"] == "INCLUDED"

    model_plan = json.loads(Path(artifacts["model_plan"]).read_text(encoding="utf-8"))
    blocked_models = [row for row in model_plan["models"] if row["status"] == "BLOCKED"]
    assert any(row["model"] in {"random_forest", "gradient_boosting"} and row["blocked_reason"] for row in blocked_models)
    assert model_plan["split_method"] == "chronological_no_shuffle"

    validation = json.loads(Path(artifacts["validation_scorecard"]).read_text(encoding="utf-8"))
    assert validation["items"]["proxy_quality"]["status"] == "WATCH"
    assert validation["items"]["performance_strength"]["status"] in {"WATCH", "FAIL"}
    assert validation["items"]["lookback_robustness"]["status"] in {"PASS", "WATCH", "FAIL"}
    assert validation["items"]["ml_lift_vs_rule"]["status"] in {"PASS", "WATCH"}

    robustness_run = json.loads(Path(artifacts["robustness_run"]).read_text(encoding="utf-8"))
    assert robustness_run["status"] == "COMPLETED"
    assert len(robustness_run["lookback_sensitivity"]["results"]) == 3
    assert {row["lookback_days"] for row in robustness_run["lookback_sensitivity"]["results"]} == {21, 63, 126}
    assert {row["cost_bps"] for row in robustness_run["cost_sensitivity"]["results"]} == {0, 5, 10, 25}
    assert {row["rebalance_frequency"] for row in robustness_run["rebalance_sensitivity"]["results"]} == {"weekly", "monthly", "quarterly"}
    assert {row["benchmark"] for row in robustness_run["benchmark_comparison"]["results"]} == {"DBC", "SPY"}
    assert robustness_run["stress_period_summary"]["status"] == "COMPLETED"
    assert robustness_run["ml_lift_vs_rule_signal"]["status"] == "COMPLETED"

    decision = json.loads(Path(artifacts["decision_scorecard"]).read_text(encoding="utf-8"))
    assert decision["recommendation"] != "Candidate"
    assert decision["candidate_allowed"] is False
    assert "robustness_status" in decision["evidence_summary"]
    assert "ml_lift_vs_rule" in decision["evidence_summary"]

    report = Path(artifacts["intelligence_report"]).read_text(encoding="utf-8")
    robustness_report = Path(artifacts["robustness_report"]).read_text(encoding="utf-8")
    for heading in (
        "## Strategy Type",
        "## Feature Rationale",
        "## ML Result Interpretation",
        "## Robustness Findings",
        "## Validation Scorecard",
        "## Next Experiment Suggestions",
    ):
        assert heading in report
    assert "## Lookback Sensitivity" in robustness_report
    assert "## ML Lift vs Rule Signal" in robustness_report


def test_robustness_blocks_without_backtest_data_and_does_not_fake_results(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    ensure_data_layout(data_root)
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)
    artifacts = result["artifacts"]

    robustness_run = json.loads(Path(artifacts["robustness_run"]).read_text(encoding="utf-8"))
    assert robustness_run["status"] == "BLOCKED"
    assert "BLOCKED_NEEDS_DATA" in robustness_run["reason"]
    lookback = json.loads(Path(artifacts["lookback_sensitivity_json"]).read_text(encoding="utf-8"))
    assert lookback["status"] == "BLOCKED"
    assert pd.read_csv(artifacts["lookback_sensitivity_csv"]).empty
    decision = json.loads(Path(artifacts["decision_scorecard"]).read_text(encoding="utf-8"))
    assert decision["recommendation"] != "Candidate"


def test_dashboard_payload_exposes_current_run_ml_and_evidence_paths(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(days=260))
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)
    factory = base_state(workstation_root)
    candidate = factory["latest_run_output"]

    assert candidate["ml_diagnostics"]["status"] == "COMPLETED"
    assert candidate["ml_model_used"] == "ridge_regression_numpy"
    assert candidate["recommendation"] == result["intelligence"]["recommendation"]
    assert candidate["recommendation"] != "Candidate"
    assert candidate["intelligence_status"] == "COMPLETED"
    assert candidate["strategy_type"] == "commodity trend / macro proxy"
    chain = candidate["source_evidence"]["artifact_chain"]
    assert chain["ml_diagnostics"] == result["artifacts"]["ml_diagnostics_run"]
    assert chain["feature_importance"] == result["artifacts"]["feature_importance_json"]
    assert chain["prediction_quality"] == result["artifacts"]["prediction_quality"]
    assert chain["leakage_check"] == result["artifacts"]["leakage_check"]
    assert chain["intelligence_report"] == result["artifacts"]["intelligence_report"]
    assert candidate["evidence_report_path"] == result["artifacts"]["evidence_report"]
    assert candidate["intelligence_report_path"] == result["artifacts"]["intelligence_report"]
    assert "ML_DIAGNOSTICS_RUN" in candidate["completed_stages"]


def test_ml_not_marked_completed_when_diagnostics_artifact_is_blocked(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(days=105))
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_current_backtest_ml(workstation_root)
    candidate = base_state(workstation_root)["latest_run_output"]
    ml = json.loads(Path(result["artifacts"]["ml_diagnostics_run"]).read_text(encoding="utf-8"))

    assert result["status"] == "COMPLETED"
    assert ml["status"] == "BLOCKED"
    assert "ML_DIAGNOSTICS_RUN" not in candidate["completed_stages"]
    assert candidate["ml_diagnostics"]["status"] == "BLOCKED"
    assert Path(result["artifacts"]["prediction_quality"]).is_file()


def test_full_current_run_job_creates_status_log_metrics_ml_and_evidence(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_csv_fixture(data_root, _fixture_prices(days=260))
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_full_current_run_job(workstation_root)

    assert result["status"] == "COMPLETED"
    artifacts = result["artifacts"]
    for key in ("job_status", "run_log", "metrics", "ml_diagnostics_run", "evidence_report"):
        assert Path(artifacts[key]).is_file(), key
    job = json.loads(Path(artifacts["job_status"]).read_text(encoding="utf-8"))
    assert job["status"] == "COMPLETED"
    assert [stage["stage"] for stage in job["stages"]] == [
        "DATA_AVAILABILITY_CHECK",
        "BACKTEST_CURRENT_RUN",
        "ML_DIAGNOSTICS",
        "EVIDENCE_REPORT",
        "INTELLIGENCE_REPORT",
    ]
    assert {stage["status"] for stage in job["stages"]} == {"COMPLETED"}
    assert "START run-full-current-run" in Path(artifacts["run_log"]).read_text(encoding="utf-8")
    candidate = base_state(workstation_root)["latest_run_output"]
    assert candidate["full_pipeline_status"] == "COMPLETED"
    assert candidate["source_evidence"]["artifact_chain"]["job_status"] == artifacts["job_status"]


def test_full_current_run_job_blocks_truthfully_without_data(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    ensure_data_layout(data_root)
    _write_current_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    result = run_full_current_run_job(workstation_root)

    assert result["status"] == "BLOCKED"
    artifacts = result["artifacts"]
    job = json.loads(Path(artifacts["job_status"]).read_text(encoding="utf-8"))
    assert job["status"] == "BLOCKED"
    assert any(stage["stage"] == "BACKTEST_CURRENT_RUN" and stage["status"] == "BLOCKED" for stage in job["stages"])
    metrics = json.loads(Path(artifacts["metrics"]).read_text(encoding="utf-8"))
    assert metrics["status"] == "BLOCKED"
    assert "sharpe" not in metrics
    ml = json.loads(Path(artifacts["ml_diagnostics_run"]).read_text(encoding="utf-8"))
    assert ml["status"] == "BLOCKED"
    candidate = base_state(workstation_root)["latest_run_output"]
    assert candidate["full_pipeline_status"] == "BLOCKED"
    assert "ML_DIAGNOSTICS_RUN" not in candidate["completed_stages"]
