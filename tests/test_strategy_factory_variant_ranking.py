from __future__ import annotations

import json
from pathlib import Path

from src.strategies.strategy_factory_variant_ranking import rank_variants


RUN_ID = "SF_RUN_RANKING_FIXTURE"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_variant(root: Path, variant_id: str, name: str, sharpe: float, annual_return: float, drawdown: float, benchmark_return: float, ml_ic: float, ml_hit: float, universe: list[str], recommendation: str = "Watch") -> None:
    variant_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    evaluation_dir = variant_dir / "evaluation"
    _write_json(
        variant_dir / "variant_spec.json",
        {
            "variant_id": variant_id,
            "variant_name": name,
            "source_run_id": RUN_ID,
            "universe_or_proxy": universe,
            "benchmark": "SPY" if "COPX" in universe else "DBC",
            "testability_status": "PROXY_ONLY",
            "data_requirements": [*universe, "SPY" if "COPX" in universe else "DBC"],
        },
    )
    _write_json(
        evaluation_dir / "variant_metrics.json",
        {
            "status": "COMPLETED",
            "sharpe": sharpe,
            "annual_return": annual_return,
            "max_drawdown": drawdown,
            "benchmark_annual_return": benchmark_return,
            "prototype_proxy_only": True,
        },
    )
    _write_json(
        evaluation_dir / "variant_ml_diagnostics_run.json",
        {
            "status": "COMPLETED",
            "prediction_quality": {"spearman_ic": ml_ic},
            "direction_quality": {"direction_hit_rate": ml_hit},
        },
    )
    _write_json(
        evaluation_dir / "variant_robustness_run.json",
        {
            "status": "COMPLETED",
            "summary": {
                "overall_status": "WATCH",
                "cost_sensitivity_status": "PASS",
                "lookback_sensitivity_status": "PASS",
                "benchmark_status": "WATCH",
            },
            "stress_periods": {
                "high_vol_period": {"sharpe": -0.2},
                "recent_period": {"sharpe": 0.4},
            },
        },
    )
    _write_json(
        evaluation_dir / "variant_decision.json",
        {
            "recommendation": recommendation,
            "candidate": False,
        },
    )


def _write_registry(root: Path) -> Path:
    variants_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants"
    variants = [
        ("COPPER_CPER_MOMENTUM_21_63_V1", "CPER Momentum 21/63", ["CPER"]),
        ("COPPER_CPER_MOMENTUM_VOL_FILTER_V1", "CPER Momentum + Volatility Filter", ["CPER"]),
        ("COPPER_CPER_DBC_RELATIVE_STRENGTH_V1", "CPER vs DBC Relative Strength", ["CPER"]),
        ("COPPER_CPER_UUP_USD_FILTER_V1", "CPER Momentum + UUP/USD Filter", ["CPER"]),
        ("COPPER_EQUITY_PROXY_TREND_COPX_XME_V1", "COPX/XME Copper Equity Proxy Trend", ["COPX", "XME"]),
        ("COMMODITY_BASKET_REGIME_FILTER_V1", "Commodity Basket Regime Filter", ["CPER"]),
    ]
    registry_rows = []
    for variant_id, name, universe in variants:
        registry_rows.append(
            {
                "variant_id": variant_id,
                "variant_name": name,
                "universe_or_proxy": universe,
                "variant_spec_path": str(variants_dir / variant_id / "variant_spec.json"),
            }
        )
    _write_json(
        variants_dir / "variant_registry.json",
        {
            "schema_version": "strategy_factory_variant_registry_v1",
            "source_run_id": RUN_ID,
            "variant_count": len(registry_rows),
            "variants": registry_rows,
        },
    )
    return variants_dir


def test_gate4_ranks_all_variants_by_composite_evidence_not_sharpe_only(tmp_path: Path) -> None:
    variants_dir = _write_registry(tmp_path)
    _write_variant(tmp_path, "COPPER_CPER_MOMENTUM_21_63_V1", "CPER Momentum 21/63", 0.2, 0.02, -0.24, 0.08, -0.03, 0.71, ["CPER"], "Modify")
    _write_variant(tmp_path, "COPPER_CPER_MOMENTUM_VOL_FILTER_V1", "CPER Momentum + Volatility Filter", 0.48, 0.05, -0.18, 0.08, 0.02, 0.80, ["CPER"], "Watch")
    _write_variant(tmp_path, "COPPER_CPER_DBC_RELATIVE_STRENGTH_V1", "CPER vs DBC Relative Strength", 0.17, 0.01, -0.31, 0.08, 0.04, 0.65, ["CPER"], "Modify")
    _write_variant(tmp_path, "COPPER_CPER_UUP_USD_FILTER_V1", "CPER Momentum + UUP/USD Filter", 0.13, 0.01, -0.30, 0.08, 0.06, 0.85, ["CPER"], "Modify")
    _write_variant(tmp_path, "COPPER_EQUITY_PROXY_TREND_COPX_XME_V1", "COPX/XME Copper Equity Proxy Trend", 0.95, 0.17, -0.26, 0.12, 0.08, 0.76, ["COPX", "XME"], "Watch")
    _write_variant(tmp_path, "COMMODITY_BASKET_REGIME_FILTER_V1", "Commodity Basket Regime Filter", 0.28, 0.03, -0.29, 0.08, -0.03, 0.78, ["CPER"], "Watch")
    before_files = {path.relative_to(variants_dir).as_posix() for path in variants_dir.rglob("*") if path.is_file()}

    ranking = rank_variants(tmp_path, RUN_ID)

    assert (variants_dir / "variant_ranking.json").is_file()
    assert (variants_dir / "variant_ranking_report.md").is_file()
    assert ranking["variant_count"] == 6
    assert len(ranking["rankings"]) == 6
    raw_sharpe_best = max(ranking["rankings"], key=lambda row: row["source_metrics"]["sharpe"])
    assert raw_sharpe_best["variant_id"] == "COPPER_EQUITY_PROXY_TREND_COPX_XME_V1"
    assert ranking["best_variant"]["variant_id"] != raw_sharpe_best["variant_id"]
    assert all(row["data_quality_score"] < 100.0 for row in ranking["rankings"])
    assert all(row["candidate_allowed"] is False for row in ranking["rankings"])
    report = (variants_dir / "variant_ranking_report.md").read_text(encoding="utf-8")
    assert "composite evidence score" in report
    assert "proxy-only" in report
    after_files = {path.relative_to(variants_dir).as_posix() for path in variants_dir.rglob("*") if path.is_file()}
    created = after_files - before_files
    assert created == {"variant_ranking.json", "variant_ranking_report.md"}


def test_gate4_etf_ranking_does_not_reuse_copper_ml_or_report_text(tmp_path: Path) -> None:
    run_id = "SF_RUN_ETF_RANKING_FIXTURE"
    variant_id = "ETF_ROTATION_63_126_TOP2_V1"
    variants_dir = tmp_path / "output" / "strategy_factory" / "runs" / run_id / "variants"
    variant_dir = variants_dir / variant_id
    evaluation_dir = variant_dir / "evaluation"
    _write_json(
        variants_dir / "variant_registry.json",
        {
            "source_run_id": run_id,
            "variant_count": 1,
            "variants": [{"variant_id": variant_id, "variant_name": "ETF Momentum Rotation 63/126 Top 2", "theme": "etf_momentum_rotation"}],
        },
    )
    _write_json(
        variant_dir / "variant_spec.json",
        {
            "variant_id": variant_id,
            "variant_name": "ETF Momentum Rotation 63/126 Top 2",
            "theme": "etf_momentum_rotation",
            "universe_or_proxy": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
            "benchmark": "SPY",
            "testability_status": "READY_TO_TEST",
        },
    )
    _write_json(evaluation_dir / "variant_metrics.json", {"status": "COMPLETED", "sharpe": 0.45, "annual_return": 0.04, "max_drawdown": -0.12, "benchmark_annual_return": 0.06, "prototype_proxy_only": False})
    _write_json(evaluation_dir / "variant_ml_diagnostics_run.json", {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available"})
    _write_json(evaluation_dir / "variant_robustness_run.json", {"status": "COMPLETED", "summary": {"overall_status": "WATCH", "cost_sensitivity_status": "PASS", "lookback_sensitivity_status": "WATCH", "benchmark_status": "WATCH"}, "stress_periods": {}})
    _write_json(evaluation_dir / "variant_decision.json", {"recommendation": "Watch", "candidate": False})

    ranking = rank_variants(tmp_path, run_id)

    row = ranking["rankings"][0]
    assert row["variant_id"] == variant_id
    assert row["ml_score"] == 0.0
    assert row["source_evidence"]["ml_evidence_status"] == "MISSING_EVIDENCE"
    report = (variants_dir / "variant_ranking_report.md").read_text(encoding="utf-8")
    assert "evaluated variants" in report
    assert "six evaluated copper variants" not in report
    assert "COPX/XME" not in report


def test_gate4_ranking_does_not_use_ambiguous_turnover_as_evidence(tmp_path: Path) -> None:
    run_id = "SF_RUN_TURNOVER_RANKING_FIXTURE"
    variants_dir = tmp_path / "output" / "strategy_factory" / "runs" / run_id / "variants"
    rows = [
        ("GENERIC_TURNOVER_HIGH_V1", 999.0),
        ("GENERIC_TURNOVER_MISSING_V1", None),
    ]
    _write_json(
        variants_dir / "variant_registry.json",
        {
            "source_run_id": run_id,
            "variant_count": len(rows),
            "variants": [{"variant_id": variant_id, "variant_name": variant_id.replace("_", " ").title()} for variant_id, _ in rows],
        },
    )
    for variant_id, turnover in rows:
        variant_dir = variants_dir / variant_id
        evaluation_dir = variant_dir / "evaluation"
        _write_json(
            variant_dir / "variant_spec.json",
            {
                "variant_id": variant_id,
                "variant_name": variant_id.replace("_", " ").title(),
                "source_run_id": run_id,
                "universe_or_proxy": ["CPER"],
                "benchmark": "DBC",
                "testability_status": "PROXY_ONLY",
            },
        )
        metrics = {
            "status": "COMPLETED",
            "sharpe": 0.25,
            "annual_return": 0.03,
            "max_drawdown": -0.12,
            "benchmark_annual_return": 0.02,
            "prototype_proxy_only": True,
        }
        if turnover is not None:
            metrics["turnover"] = turnover
        _write_json(evaluation_dir / "variant_metrics.json", metrics)
        _write_json(evaluation_dir / "variant_ml_diagnostics_run.json", {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE"})
        _write_json(evaluation_dir / "variant_robustness_run.json", {"status": "COMPLETED", "summary": {"overall_status": "WATCH", "cost_sensitivity_status": "PASS", "lookback_sensitivity_status": "PASS", "benchmark_status": "WATCH"}, "stress_periods": {}})
        _write_json(evaluation_dir / "variant_decision.json", {"recommendation": "Watch", "candidate": False})

    ranking = rank_variants(tmp_path, run_id)

    scored = {row["variant_id"]: row for row in ranking["rankings"]}
    assert scored["GENERIC_TURNOVER_HIGH_V1"]["performance_score"] == scored["GENERIC_TURNOVER_MISSING_V1"]["performance_score"]
    assert scored["GENERIC_TURNOVER_HIGH_V1"]["evidence_score"] == scored["GENERIC_TURNOVER_MISSING_V1"]["evidence_score"]
