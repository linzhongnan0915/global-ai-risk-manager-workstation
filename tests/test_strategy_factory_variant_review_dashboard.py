from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler
from src.strategies.strategy_factory_plugin import base_state


RUN_ID = "SF_RUN_VARIANT_REVIEW_FIXTURE"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_review_fixture(root: Path) -> None:
    variants_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants"
    variant_rows = []
    ranking_rows = []
    ids = [
        "COPPER_CPER_MOMENTUM_21_63_V1",
        "COPPER_CPER_MOMENTUM_VOL_FILTER_V1",
        "COPPER_CPER_DBC_RELATIVE_STRENGTH_V1",
        "COPPER_CPER_UUP_USD_FILTER_V1",
        "COPPER_EQUITY_PROXY_TREND_COPX_XME_V1",
        "COMMODITY_BASKET_REGIME_FILTER_V1",
    ]
    for idx, variant_id in enumerate(ids, start=1):
        variant_dir = variants_dir / variant_id
        evaluation_dir = variant_dir / "evaluation"
        name = variant_id.replace("_", " ").title()
        spec = {
            "variant_id": variant_id,
            "variant_name": name,
            "source_run_id": RUN_ID,
            "thesis": "Fixture copper proxy thesis.",
            "signal_formula": "Long proxy when trend condition is true.",
            "universe_or_proxy": ["COPX", "XME"] if "EQUITY" in variant_id else ["CPER"],
            "benchmark": "SPY" if "EQUITY" in variant_id else "DBC",
            "features": ["momentum_21d", "momentum_63d"],
            "data_requirements": ["CPER", "DBC"],
            "testability_status": "PROXY_ONLY",
        }
        _write_json(variant_dir / "variant_spec.json", spec)
        _write_json(
            evaluation_dir / "variant_metrics.json",
            {
                "status": "COMPLETED",
                "sharpe": 0.1 * idx,
                "annual_return": 0.01 * idx,
                "max_drawdown": -0.1,
                "benchmark_annual_return": 0.08,
                "prototype_proxy_only": True,
            },
        )
        _write_json(
            evaluation_dir / "variant_ml_diagnostics_run.json",
            {
                "status": "COMPLETED",
                "model": "ridge_regression_numpy",
                "prediction_quality": {"spearman_ic": 0.01 * idx},
                "direction_quality": {"direction_hit_rate": 0.5 + idx / 100},
            },
        )
        _write_json(
            evaluation_dir / "variant_robustness_run.json",
            {"status": "COMPLETED", "summary": {"overall_status": "WATCH", "cost_sensitivity_status": "PASS", "lookback_sensitivity_status": "PASS", "benchmark_status": "WATCH"}},
        )
        _write_json(
            evaluation_dir / "variant_decision.json",
            {
                "variant_id": variant_id,
                "recommendation": "Watch" if idx == 1 else "Modify",
                "candidate": False,
                "reason": "Proxy-only evidence blocks Candidate.",
            },
        )
        (evaluation_dir / "variant_evidence_report.md").write_text(f"# Evidence {variant_id}\n", encoding="utf-8")
        variant_rows.append({"variant_id": variant_id, "variant_name": name, "universe_or_proxy": spec["universe_or_proxy"], "benchmark": spec["benchmark"]})
        ranking_rows.append(
            {
                "rank": idx,
                "variant_id": variant_id,
                "variant_name": name,
                "evidence_score": 60 - idx,
                "performance_score": 50,
                "robustness_score": 45,
                "ml_score": 55,
                "data_quality_score": 65,
                "risk_penalty": 30,
                "final_recommendation": "Watch" if idx == 1 else "Modify",
                "candidate_allowed": False,
                "reason": "proxy-only data prevents Candidate status.",
            }
        )
    _write_json(variants_dir / "variant_registry.json", {"source_run_id": RUN_ID, "variant_count": len(variant_rows), "variants": variant_rows})
    _write_json(
        variants_dir / "variant_ranking.json",
        {
            "source_run_id": RUN_ID,
            "variant_count": len(ranking_rows),
            "best_variant": ranking_rows[0],
            "rankings": ranking_rows,
        },
    )
    (variants_dir / "variant_ranking_report.md").write_text("# Ranking Report\n", encoding="utf-8")


def test_strategy_factory_state_exposes_variant_review_payload(tmp_path: Path) -> None:
    _write_review_fixture(tmp_path)

    state = base_state(tmp_path)
    review = state["variant_review"]

    assert review["status"] == "COMPLETED"
    assert review["run_id"] == RUN_ID
    assert review["variant_count"] == 6
    assert review["best_variant"]["variant_id"] == "COPPER_CPER_MOMENTUM_21_63_V1"
    assert review["ranking_summary"]
    assert len(review["variant_cards"]) == 6
    assert review["ranking_report_path"].endswith("variant_ranking_report.md")
    assert review["ranking_report_url"].startswith("/api/strategy-factory/variants/ranking-report")
    assert all(card["decision"]["candidate_allowed"] is False for card in review["variant_cards"])
    assert review["candidate_gating"]["add_to_candidate_portfolio_enabled"] is False
    assert review["candidate_gating"]["override_required"] is True
    first = review["variant_cards"][0]
    assert first["decision"]["recommendation"] == "Watch"
    assert first["ml_diagnostics"]["summary"]
    assert first["evidence_report_url"].endswith(f"/evidence?run_id={RUN_ID}")


def _write_picker_variant(root: Path, run_id: str, variant_id: str, *, strategy_name: str, theme: str, proceed: bool = True) -> None:
    variants_dir = root / "output" / "strategy_factory" / "runs" / run_id / "variants"
    variant_dir = variants_dir / variant_id
    evaluation_dir = variant_dir / "evaluation"
    _write_json(root / "output" / "strategy_factory" / "runs" / run_id / "run_manifest.json", {"run_id": run_id, "selected_material_names": [f"{run_id}_material.md"], "strategy_factory_theme": theme})
    _write_json(
        variant_dir / "variant_spec.json",
        {
            "variant_id": variant_id,
            "variant_name": strategy_name,
            "strategy_name": strategy_name,
            "theme": theme,
            "thesis": f"{strategy_name} fixture thesis.",
            "signal_formula": f"{variant_id} fixture signal.",
            "universe_or_proxy": ["AAA", "BBB"],
            "benchmark": "SPY",
        },
    )
    _write_json(evaluation_dir / "variant_metrics.json", {"status": "COMPLETED", "theme": theme, "sharpe": 0.7, "annual_return": 0.11, "max_drawdown": -0.09, "rows": 64})
    _write_json(evaluation_dir / "variant_ml_diagnostics_run.json", {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available"})
    _write_json(evaluation_dir / "variant_robustness_run.json", {"status": "COMPLETED", "summary": {"overall_status": "WATCH"}})
    _write_json(evaluation_dir / "variant_decision.json", {"recommendation": "Watch", "candidate": False, "reason": "Fixture watch decision."})
    _write_json(evaluation_dir / "variant_evidence_manifest.json", {"theme": theme, "evidence_status": "EVIDENCE_AVAILABLE", "backtest_status": "COMPLETED"})
    _write_json(evaluation_dir / "variant_readiness_status.json", {"theme": theme, "automation_ready": proceed, "automation_block_reason": "" if proceed else "FIXTURE_BLOCKED"})
    (evaluation_dir / "variant_evidence_report.md").write_text(f"# Evidence {strategy_name}\n", encoding="utf-8")
    _write_json(variants_dir / "variant_registry.json", {"source_run_id": run_id, "variant_count": 1, "variants": [{"variant_id": variant_id, "variant_name": strategy_name, "theme": theme}]})
    _write_json(variants_dir / "variant_ranking.json", {"source_run_id": run_id, "variant_count": 1, "best_variant": {"variant_id": variant_id}, "rankings": [{"rank": 1, "variant_id": variant_id, "variant_name": strategy_name, "evidence_score": 61, "final_recommendation": "Watch", "candidate_allowed": False}]})


def test_candidate_picker_is_registry_driven_and_dynamic(tmp_path: Path) -> None:
    _write_picker_variant(tmp_path, "SF_RUN_PICKER_A", "DYNAMIC_ALPHA_A_V1", strategy_name="Dynamic Alpha A", theme="unknown_review_required")
    _write_picker_variant(tmp_path, "SF_RUN_PICKER_B", "DYNAMIC_ALPHA_B_V1", strategy_name="Dynamic Alpha B", theme="us_stock_custom_research")

    picker = base_state(tmp_path)["candidate_picker"]
    names = {row["strategy_name"] for row in picker["candidates"]}
    themes = {row["theme"] for row in picker["candidates"]}

    assert picker["schema_version"] == "strategy_factory_candidate_picker_v1"
    assert names == {"Dynamic Alpha A", "Dynamic Alpha B"}
    assert themes == {"unknown_review_required", "us_stock_custom_research"}
    assert all(row["evidence_report_url"] for row in picker["candidates"])
    assert all(row["proceed_status"] == "PROCEED_ELIGIBLE" for row in picker["candidates"])

    (tmp_path / "output" / "strategy_factory" / "runs" / "SF_RUN_PICKER_A" / "variants" / "variant_registry.json").unlink()
    picker_after_remove = base_state(tmp_path)["candidate_picker"]
    remaining = {row["strategy_name"] for row in picker_after_remove["candidates"]}

    assert remaining == {"Dynamic Alpha B"}
    dashboard_source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    assert "Dynamic Alpha A" not in dashboard_source
    assert "Dynamic Alpha B" not in dashboard_source
    assert "COPX" not in dashboard_source
    assert "XME" not in dashboard_source


def test_strategy_factory_state_exposes_etf_missing_ml_without_copper_summary(tmp_path: Path) -> None:
    run_id = "SF_RUN_ETF_REVIEW_FIXTURE"
    variant_id = "ETF_ROTATION_63_126_TOP2_V1"
    variants_dir = tmp_path / "output" / "strategy_factory" / "runs" / run_id / "variants"
    variant_dir = variants_dir / variant_id
    evaluation_dir = variant_dir / "evaluation"
    _write_json(
        variant_dir / "variant_spec.json",
        {
            "variant_id": variant_id,
            "variant_name": "ETF Momentum Rotation 63/126 Top 2",
            "theme": "etf_momentum_rotation",
            "strategy_name": "ETF Momentum Rotation 63/126 Top 2",
            "thesis": "Cross-asset ETF momentum rotation.",
            "signal_formula": "Rank ETF universe by 63d plus 126d momentum monthly.",
            "universe_or_proxy": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
            "benchmark": "SPY",
            "features": ["momentum_63d", "momentum_126d"],
        },
    )
    _write_json(evaluation_dir / "variant_metrics.json", {"status": "COMPLETED", "sharpe": 0.4, "annual_return": 0.05, "max_drawdown": -0.1, "benchmark_annual_return": 0.06, "rows": 180})
    _write_json(evaluation_dir / "variant_ml_diagnostics_run.json", {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available"})
    _write_json(evaluation_dir / "variant_robustness_run.json", {"status": "COMPLETED", "summary": {"overall_status": "WATCH"}})
    _write_json(evaluation_dir / "variant_decision.json", {"recommendation": "Watch", "candidate": False})
    (evaluation_dir / "variant_evidence_report.md").write_text("# ETF Evidence\n", encoding="utf-8")
    _write_json(variants_dir / "variant_registry.json", {"source_run_id": run_id, "variant_count": 1, "variants": [{"variant_id": variant_id, "variant_name": "ETF Momentum Rotation 63/126 Top 2", "theme": "etf_momentum_rotation"}]})
    _write_json(variants_dir / "variant_ranking.json", {"source_run_id": run_id, "variant_count": 1, "best_variant": {"variant_id": variant_id}, "rankings": [{"rank": 1, "variant_id": variant_id, "evidence_score": 55, "final_recommendation": "Watch", "candidate_allowed": False}]})

    review = base_state(tmp_path)["variant_review"]
    card = review["variant_cards"][0]

    assert card["theme"] == "etf_momentum_rotation"
    assert card["strategy_name"] == "ETF Momentum Rotation 63/126 Top 2"
    assert card["ml_diagnostics"]["summary"] == "No ML evidence available"
    assert card["ml_diagnostics"]["ml_evidence_status"] == "MISSING_EVIDENCE"
    assert "ridge_regression_numpy" not in json.dumps(card)
    assert "COPX" not in json.dumps(card)
    assert "XME" not in json.dumps(card)


def test_strategy_factory_state_exposes_us_stock_readiness_and_missing_ml_truth(tmp_path: Path) -> None:
    run_id = "SF_RUN_US_STOCK_REVIEW_FIXTURE"
    variant_id = "US_STOCK_MOMENTUM_12_1_TOP50_V1"
    variants_dir = tmp_path / "output" / "strategy_factory" / "runs" / run_id / "variants"
    variant_dir = variants_dir / variant_id
    evaluation_dir = variant_dir / "evaluation"
    _write_json(
        variant_dir / "variant_spec.json",
        {
            "variant_id": variant_id,
            "variant_name": "U.S. Stock Momentum 12-1 Top 50",
            "theme": "us_stock_cross_sectional_momentum_quality",
            "strategy_name": "U.S. Stock Momentum 12-1 Top 50",
            "generated_from_material": True,
            "source_material_path": "strategy_factory/intake_queue/examples/us_stock_momentum_quality_material.md",
            "source_material_hash": "fixture_hash",
            "thesis": "U.S. stock cross-sectional momentum.",
            "signal_formula": "Rank stocks by 252d momentum excluding recent 21d.",
            "universe_or_proxy": ["AAPL", "MSFT", "NVDA", "AMZN", "META"],
            "benchmark": "SPY",
            "features": ["momentum_252d_ex_recent_21d", "quality_proxy_missing_evidence"],
        },
    )
    _write_json(evaluation_dir / "variant_metrics.json", {"status": "COMPLETED", "sharpe": 0.4, "annual_return": 0.05, "max_drawdown": -0.1, "volatility": 0.18, "turnover": 0.2, "rows": 180})
    _write_json(evaluation_dir / "variant_ml_diagnostics_run.json", {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available"})
    _write_json(evaluation_dir / "variant_robustness_run.json", {"status": "COMPLETED", "summary": {"overall_status": "WATCH"}})
    _write_json(evaluation_dir / "variant_decision.json", {"recommendation": "Watch", "candidate": False, "automation_ready": True, "automation_block_reason": "BACKTEST_METRICS_AVAILABLE; ML_MISSING_BUT_NOT_BLOCKING"})
    _write_json(evaluation_dir / "variant_evidence_manifest.json", {"evidence_status": "EVIDENCE_AVAILABLE", "backtest_status": "COMPLETED", "ml_truth_status": "MISSING_EVIDENCE", "ml_summary": "No ML evidence available", "generated_from_material": True})
    _write_json(evaluation_dir / "variant_readiness_status.json", {"automation_ready": True, "automation_block_reason": "BACKTEST_METRICS_AVAILABLE; ML_MISSING_BUT_NOT_BLOCKING", "generated_from_material": True, "display_message": "Automation-ready evidence gate passed.", "evidence_artifact_path": str(evaluation_dir / "variant_evidence_report.md")})
    (evaluation_dir / "variant_evidence_report.md").write_text("# U.S. Stock Evidence\n", encoding="utf-8")
    _write_json(variants_dir / "variant_registry.json", {"source_run_id": run_id, "variant_count": 1, "variants": [{"variant_id": variant_id, "variant_name": "U.S. Stock Momentum 12-1 Top 50", "theme": "us_stock_cross_sectional_momentum_quality"}]})
    _write_json(variants_dir / "variant_ranking.json", {"source_run_id": run_id, "variant_count": 1, "best_variant": {"variant_id": variant_id}, "rankings": [{"rank": 1, "variant_id": variant_id, "evidence_score": 55, "final_recommendation": "Watch", "candidate_allowed": False, "automation_ready": True, "automation_block_reason": "BACKTEST_METRICS_AVAILABLE; ML_MISSING_BUT_NOT_BLOCKING"}]})

    card = base_state(tmp_path)["variant_review"]["variant_cards"][0]

    assert card["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert card["evidence_manifest"]["evidence_status"] == "EVIDENCE_AVAILABLE"
    assert card["ml_diagnostics"]["ml_evidence_status"] == "MISSING_EVIDENCE"
    assert card["readiness"]["automation_ready"] is True
    assert card["automation_ready"] is True
    assert card["proceed_status"] == "PROCEED_ELIGIBLE"
    assert card["automation_block_reason"] == "BACKTEST_METRICS_AVAILABLE; ML_MISSING_BUT_NOT_BLOCKING"
    assert "ridge_regression_numpy" not in json.dumps(card)
    assert "COPX" not in json.dumps(card)
    assert "XME" not in json.dumps(card)


def test_dashboard_source_contains_variant_review_panel() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    assert "Generated Strategy Candidate Pool" in source
    assert "factoryStrategyCandidatePicker" in source
    assert "factoryCandidatePickerPayload" in source
    assert "data-factory-picker-filter" in source
    assert "Ready to Proceed" in source
    assert "Select / Load Candidate" in source
    assert "factory-candidate-picker-table" in source
    assert "Strategy Name" in source
    assert "Theme / Family" in source
    assert "Source Material" in source
    assert "Portfolio State" in source
    assert "Variant Ranking" in source
    assert "factoryVariantReviewPanel" in source
    assert "candidate_allowed" in source
    assert "Add to Candidate Portfolio disabled" in source
    assert "Generated from material" in source
    assert "Automation readiness" in source
    assert "Automation block reason" in source
    assert "Evidence artifact path" in source
    assert "Not automation-ready: evidence/backtest missing." in source
    assert "Proceed with Strategy" in source
    assert "PROCEED_ELIGIBLE" in source


def test_dashboard_turnover_display_uses_annualized_multiple_not_percent_format() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "factoryTurnoverDisplay" in source
    assert "factoryTurnoverYears" in source
    assert "Turnover / year" in source
    assert "x / year" in source
    assert "ANNUALIZED_ONE_WAY_MULTIPLE" in source
    assert "average_rebalance_turnover" in source
    assert "rebalance_frequency_per_year" in source
    assert "Raw artifact turnover is cumulative one-way turnover" in source
    assert "Turnover definition unavailable" in source
    assert 'factoryPolishValue(m.turnover,"percent")' not in source
    assert 'factoryArtifactField(m.turnover,paths.metrics,"percent")' not in source
    assert "1,600.00%" not in source


def test_dashboard_data_quality_renders_compact_badges_with_raw_tooltip() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "factoryDataQualityBadges" in source
    assert "PUBLIC FALLBACK" in source
    assert "NOT PIT" in source
    assert "NOT SURVIVORSHIP-FREE" in source
    assert 'title="${UI.escapeHtml(text)}"' in source
    assert "${factoryDataQualityBadges(m.data_quality_status)}" in source
    assert "Full data quality enum" in source


def test_best_variant_evidence_card_is_compact_and_lineage_collapsed() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")

    assert "compact-evidence-card" in source
    assert "compact-best-evidence-section" in source
    assert "factory-evidence-clamp two-line-clamp" in source
    assert "factory-evidence-clamp one-line-clamp" in source
    assert "Show full thesis / signal / readiness" in source
    assert "Show evidence lineage & readiness details" in source
    assert "Evidence artifact: ${artifactPath&&artifactPath!==\"Missing Evidence\"?\"available\":\"Missing Evidence\"}" in source
    assert "Evidence artifact path" in source
    assert "Automation block reason" in source
    assert ".factory-evidence-metrics.compact" in css
    assert ".compact-evidence-card" in css
    assert ".one-line-clamp" in css
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css


def test_legacy_dashboard_runtime_does_not_default_shadow_counts_to_fixed_16_17() -> None:
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    assert "configured_strategy_count || 16" not in source
    assert "previous_active_count || 16" not in source
    assert "current_active_count || 17" not in source
    assert 'shadow.configured_strategy_count ?? "n/a"' in source
    assert 'shadow.previous_active_count ?? "n/a"' in source
    assert 'shadow.current_active_count ?? "n/a"' in source


def test_dashboard_strategy_factory_operator_workflow_defaults_are_compact() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "Compact Intake Bar" in source
    assert "factoryMaterialLibraryExpanded" in source
    assert "Upload materials" in source
    assert "Run Selected Batch" in source
    assert "Run Full Pipeline" in source
    assert "Expand Material Library" in source
    assert "Collapse Material Library" in source
    assert "Run Decision Summary" in source
    assert "Variant Ranking Table" in source
    assert "Selected Variant / Evidence Workspace" in source
    assert "Selected Strategy Action" in source
    assert "Strict gate is separate from simulated portfolio workflow." in source
    assert "Show technical lineage" in source
    assert "factoryCollapsedCandidateOutputs" in source
    assert "<summary>Historical Alpha Candidates" in source
    assert "<summary>Prototype Seed Fallback" in source
    assert "Debug / Archives" in source
    assert "Global idea registry debug" in source


def test_dashboard_operator_view_uses_latest_run_pipeline_source() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "factoryPipelineSummary" in source
    assert 'factoryRunHasArtifact(f,"job_status")' in source
    assert 'factoryRunHasArtifact(f,"backtest_run")' in source
    assert 'factoryRunHasArtifact(f,"ml_diagnostics_run")' in source
    assert 'factoryRunHasArtifact(f,"evidence_report")' in source
    assert "Same latest current-run source as summary" in source


def test_dashboard_operator_view_orders_intake_ranking_and_archives() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    page_start = source.rfind("function strategyFactoryPage")
    page_source = source[page_start:]

    assert page_source.index("factoryCompactIntakeBar") < page_source.index("factoryRunDecisionSummary")
    assert page_source.index("factoryRunDecisionSummary") < page_source.index("factoryBestVariantEvidenceCard")
    assert page_source.index("factoryBestVariantEvidenceCard") < page_source.index("factoryVariantReviewPanel")
    assert page_source.index("factoryVariantReviewPanel") < page_source.index("factorySelectedVariantWorkspace")
    assert page_source.index("factorySelectedVariantWorkspace") < page_source.index("factoryPortfolioAdmissionPanel")
    assert page_source.index("factoryPortfolioAdmissionPanel") < page_source.index("factoryStrategyCandidatePicker")
    assert page_source.index("factoryStrategyCandidatePicker") < page_source.index("factoryArchivesDebugPanel")
    archives_start = source.rfind("function factoryCollapsedCandidateOutputs")
    archives_source = source[archives_start:]
    assert archives_source.index("Collapsed Candidate Archives") < archives_source.index("<summary>Historical Alpha Candidates")


def test_dashboard_operator_view_collapses_noisy_candidate_cards_by_default() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "<summary>Current Run Candidate Cards" in source
    assert "Intermediate current-run candidates - not ranked variants." in source
    assert "This candidate debug view is separate from selected ranked variant review." in source
    assert "<summary>Historical Alpha Candidates" in source
    assert "<summary>Prototype Seed Fallback" in source
    assert "Fallback only; hidden whenever current_run or variant ranking exists." in source


def test_dashboard_operator_view_candidate_admission_disabled_reason() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "Candidate admission disabled: proxy-only data and robustness/risk limitations." in source
    assert "Add to Portfolio Candidates" in source
    assert "Activate Strategy" in source
    assert "Strategy Factory Approval & Activation" in source
    assert "Active Unallocated" in source or "ACTIVE_UNALLOCATED" in source
    assert "candidate_allowed" in source
    assert "Strict gate details" in source
    assert "Selected Strategy Action" in source
    assert "View in Strategy Monitor" in source
    assert "factoryPortfolioCandidatesPayload" in source
    assert "factoryPortfolioCandidateEligibility" in source
    assert "factoryPortfolioCandidateCard" in source
    assert "factoryRunPortfolioCandidateAction" in source
    assert "data-factory-portfolio-candidate-confirm" in source
    assert "data-factory-activation-confirm" in source
    assert "Check confirmation to enable Proceed with Strategy." in source
    assert "Activation confirmation checked. Activate Strategy is enabled." in source
    assert "I want to add this strategy to the portfolio candidate list." in source
    assert "Activate this strategy with 0.00% initial allocation and make it eligible for rebalance recommendations." in source
    assert "Added to Portfolio Candidates" in source
    assert "Activated strategy:" in source
    assert "Display only" in source
    assert "Display-only label; canonical identity uses strategy_uid." in source
    assert "strategy_uid" in source
    assert "Assigned strategy ID" not in source
    assert '"/api/strategy-factory/portfolio-candidates/add"' in source
    assert '"/api/strategy-factory/portfolio-candidates/activate"' in source
    assert "live_trading:false" in source
    admission_source = Path("src/strategies/strategy_factory_admission.py").read_text(encoding="utf-8")
    assert "IN_PORTFOLIO_CANDIDATES" in admission_source
    assert "ACTIVE_UNALLOCATED" in admission_source
    assert "NEEDS_USER_CONFIRMATION" in admission_source
    assert "RECOMMENDATION_PENDING" in admission_source
    assert "NONE_WHILE_CURRENT_WEIGHT_ZERO" in admission_source
    assert "eligible_for_optimizer" in admission_source
    assert "eligible_for_rebalance" in admission_source
    assert "strategy_uid" in admission_source
    assert "display_label" in admission_source
    assert "live_trading" in admission_source
    assert "brokerage_execution" in admission_source
    assert "View Evidence" in source
    assert "No NAV/P&L impact until nonzero rebalance." in source
    assert "Pending approval rows do not count as active." in source
    assert "Active Unallocated rows require USER_UI confirmation lineage" in source
    assert '"/api/strategy-factory/admission/generate-allocation-draft"' in source
    assert "Add to Candidate Portfolio disabled" in source
    assert "Current best variant admission" in source
    assert "Existing old drafts" in source
    assert "Future eligible flow: Add Candidate -> Allocation Draft -> Paper Apply -> Combined recompute." in source
    assert "READY_FOR_PAPER_PORTFOLIO" in source
    assert "factoryAdmissionTimeline" in source
    assert "factoryAdmissionPrimaryCta" in source
    assert "factoryAdmissionUiState" in source
    assert "BLOCKED" in source
    assert "IN_CANDIDATE_PORTFOLIO" in source
    assert "RISK_REVIEW_PASSED" in source
    assert "ALLOCATION_DRAFT_READY" in source
    assert "AWAITING_USER_CONFIRMATION" in source
    assert "PAPER_APPLIED" in source
    assert "data-factory-admission-action" in source
    assert "/api/strategy-factory/admission/" in source
    assert "Apply to paper portfolio only. No live trading." in source
    assert "Paper apply requires explicit checkbox confirmation" in source
    assert "Combined recompute request" in source
    assert "Strategy Monitor" in source
    assert "PENDING_NEXT_PAPER_REFRESH" in source
    assert "PENDING_COMBINED_RECOMPUTE" in source
    assert "PENDING_RISK_RECALCULATION" in source
    assert "Portfolio NAV/P&amp;L" in source
    assert "Estimated transaction cost" in source
    assert "Combined recompute requested" in source


def test_dashboard_phase2_dynamic_strategy_universe_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "phase2StrategyFactoryRows" in source
    assert "isCombinedStrategyRow" in source
    assert "ordinaryActiveRows" in source
    assert "combinedActiveRows" in source
    assert "activeCountBreakdown" in source
    assert "!isCombinedStrategyRow(s)" in source
    assert "phase2ApplyUniverseInventory" in source
    assert "ordinary_active_count" in source
    assert "combined_active_count" in source
    assert "top_level_active_count" in source
    assert "Ordinary Active" in source
    assert "Top-Level Active" in source
    assert "Composite row; no ordinary display label" in source or "Combined" in source
    assert "pending approval excluded" in source
    assert "Candidate / Pending" in source
    assert "ACTIVE_UNALLOCATED_WAITING_REBALANCE" in source
    assert "current_strategy_universe_count" in source
    assert "allocated_active_strategies" in source
    assert "active_unallocated_strategies" in source
    assert "portfolio_candidates" in source
    assert "optimizer_eligible_strategies" in source
    assert "combined_future_constituents" in source
    assert "Combined Current uses effective current weights" in source
    assert "Initial recommendation for newly activated Strategy Factory strategy" in source
    assert "ZERO_WEIGHT_NO_NAV_PNL_IMPACT" in source
    assert "Strategy performance" in source


def test_dashboard_phase1_recommendation_only_rows_expose_evidence_lineage() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "recommendationRecordForStrategy" in source
    assert "strategy_name" in source
    assert "strategy_uid" in source
    assert "canonical_status" in source
    assert "current_weight" in source
    assert "recommended_weight" in source
    assert "proposed_weight" in source
    assert "estimated_trade" in source
    assert "estimated_transaction_cost" in source
    assert "recommendation_reason" in source
    assert "evidence_status" in source
    assert "data_quality" in source
    assert "ml_status" in source
    assert "action_status" in source
    assert "recommendationDataQualityBadges" in source
    assert "PUBLIC FALLBACK" in source
    assert "NOT PIT" in source
    assert "NOT SURVIVORSHIP-FREE" in source
    assert "No ML evidence available" in source
    assert "STARTER_RECOMMENDATION_REVIEW_REQUIRED" in source
    assert "capped starter recommendation for USER_UI-approved active-unallocated Strategy Factory strategy" in source
    assert "No live orders, official ledger rows, or NAV/P&amp;L changes are created here." in source
    assert "live_trading:false" in source
    assert "brokerage_execution:false" in source
    assert "execution_enabled:false" in source


def test_dashboard_phase1_recommendations_do_not_default_new_strategies_to_equal_weight() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    final_source = source[source.rfind("function phase2StarterRecommendedWeight") :]

    assert "phase2StarterRecommendedWeight" in source
    assert "Math.min(.005" in final_source
    assert "1/total" not in final_source
    assert "baseline recommendation" not in final_source
    assert "capped starter recommendation" in final_source


def test_dashboard_command_center_contributors_are_dynamic_real_performance_top_bottom_five() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    contributors_source = source[source.find("function contributors") : source.find("function commandRecommendation")]

    assert "dynamic top/bottom 5" in contributors_source
    assert ".slice(0,5)" in contributors_source
    assert "Number.isFinite(Number(r[basis]))" in contributors_source
    assert "!isCombinedStrategyRow(r)" in contributors_source
    assert "!r.strategy_factory_phase2" in contributors_source
    assert "No ${t} strategies with real daily performance available." in contributors_source
    assert "active unallocated rows show $0 / N/A until rebalance allocation" in source
    assert "Top contributors & detractors" in source
    assert "Derived from active strategy families" in source
    assert "phase2CommandCenterSummary" in source
    assert "Current membership & allocation" in source
    assert "Combined Current: Unchanged" in source
    assert "17 active strategies" not in source
    assert "Strategy Factory Phase 1 rows shown separately" not in source[source.rfind("function strategyMonitorPage") :]


def test_dashboard_ui_correction_compact_kpi_and_display_only_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")

    assert "command-status-strip compact-kpi-strip" in source
    assert "Portfolio NAV" in source
    assert "Daily P&L" in source
    assert "Top-Level Active" in source
    assert "Active Unallocated" in source
    assert "Pending Approval" in source
    assert "Recommendation/Rebalance" in source
    assert "Txn Cost / 5bps" in source
    assert "Show secondary diagnostics" not in source
    assert "Show strategy universe diagnostics" not in source
    assert "Current membership & allocation" in source
    assert "Top contributors & detractors" in source
    assert "Strategy performance" in source
    assert "Rebalance decision center" in source
    assert "Strategy Family Mix" in source
    assert "height:44px" in css
    assert "grid-template-rows:245px 225px 165px 150px" in css
    assert "Display only" in source
    assert "Display-only label; canonical identity uses strategy_uid." in source
    assert "Display label</span>" not in source


def test_dashboard_risk_factor_dynamic_universe_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")

    assert "riskDynamicUniverseRows" in source
    assert "currentActiveRows(c).forEach" in source
    assert "riskDynamicMissingRowFromStrategy" in source
    assert "ACTIVE_UNALLOCATED_ZERO_WEIGHT" in source
    assert "Missing Evidence / Pending Rebalance / No portfolio impact" in source
    assert "ACTIVE_UNALLOCATED_NO_POSITION_IMPACT" in source
    assert "No borrowed factor exposure; no fake metrics; pending rebalance." in source
    assert "Missing values remain explicit labels, not zero" in source
    assert "active-unallocated rows are 0.00% current weight and no portfolio impact until rebalance" in source
    assert "risk_factor_market_proxy_table + dynamic active universe" in source
    assert "risk_factor_big_table fallback + dynamic active universe" in source
    assert "ordinary ${counts.ordinary_active_count} + Combined ${counts.combined_active_count}" in source
    assert "phase2-unallocated-row" in css


def test_strategy_monitor_and_factory_action_ui_polish_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")

    assert "Top-Level Active = Ordinary Active + Combined" in source
    assert "Pending approval and portfolio candidates are not active strategies." in source
    assert "strategy-monitor-status-summary" in source
    assert "strategy-monitor-page list-first" in source
    assert "${strategyPanel()}${portfolioCandidateStrategyMonitorSection()}" in source
    assert "Strategy Factory Approval & Activation" in source
    assert "No active unallocated strategies yet." in source
    assert "Candidate / Pending" in source
    assert "Recommendation Pending" in source
    assert "Rebalance Eligible" in source
    assert "Approve & Activate Strategy" in source
    assert "View in Allocation & Rebalance" in source
    start = source.rfind("function strategyMonitorPage")
    end = source.find("function page", start)
    final_monitor_source = source[start:end]
    assert "compact-count-kpis" not in final_monitor_source
    assert "MetricCard" not in final_monitor_source
    assert "compact-empty-state" in css
    assert "compact-monitor-table" in css
    assert "table-cell-truncate" in css
    assert ".strategy-monitor-status-summary" in css


def test_strategy_monitor_approve_activate_button_uses_real_activation_flow() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")
    smoke = Path("scripts/verify_strategy_factory_operator_view.py").read_text(encoding="utf-8")

    assert "data-monitor-approve-activate" in source
    assert "approvePortfolioCandidateFromMonitor" in source
    assert "Activate this strategy with 0.00% current allocation and make it eligible for rebalance recommendations?" in source
    assert '"/api/strategy-factory/portfolio-candidates/activate"' in source
    assert 'activation_source:"USER_UI"' in source
    assert "smoke_only:false" in source
    assert "await refreshStrategyFactoryState()" in source
    assert "state.monitorActionMessage" in source
    assert "Strategy Monitor activation failed" in source
    assert "console.error" in source
    assert "monitor-action-message" in css
    assert "approve-activate-from-strategy-monitor" in smoke


def test_strategy_detail_drawer_formats_kpis_status_and_timestamps() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")

    assert "formatEtTimestamp" in source
    assert "formatToParts" in source
    assert "`${parts.month} ${parts.day}, ${parts.year} ${parts.hour}:${parts.minute} ${parts.dayPeriod} ET`" in source
    assert 'timeZone:"America/New_York"' in source
    assert 'month:"short"' in source
    assert 'hour:"numeric"' in source
    assert "strategy-detail-kpis" in source
    assert "drawer-governance-status" in source
    assert "drawerStatusItem(\"Execution Type\"" in source
    assert "drawerStatusItem(\"Execution Verification\"" in source
    assert "drawerStatusItem(\"Live Fill\"" in source
    assert "Paper / Next Open" in source
    assert "Paper Provenance Pending" in source
    assert "No Live Fill" in source

    overview_start = source.find("function drawerOverview")
    overview_end = source.find("function drawerPerformance", overview_start)
    overview_source = source[overview_start:overview_end]
    assert "drawerKpi(\"Sleeve Weight\"" in overview_source
    assert "drawerKpi(\"Daily P&L\"" in overview_source
    assert "drawerKpi(\"Operational NAV\"" in overview_source
    assert "<section class=\"drawer-kpis strategy-detail-kpis\">" in overview_source
    assert "Execution Type</span><strong>" not in overview_source
    assert "Execution Verification</span><strong>" not in overview_source
    assert "Live Fill</span><strong>" not in overview_source

    assert ".strategy-detail-kpis.drawer-kpis{grid-template-columns:repeat(2" in css
    assert ".drawer-governance-status .drawer-status-grid{display:grid;grid-template-columns:1fr 1fr" in css
    assert "@media(max-width:640px){.strategy-detail-kpis.drawer-kpis,.drawer-governance-status .drawer-status-grid{grid-template-columns:1fr}" in css


def test_intraday_session_display_separates_calendar_and_trading_session() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "tradingSessionInfo" in source
    assert "c.session_state||null" in source
    assert 'source:"backend"' in source
    assert 'source:"frontend_fallback"' in source
    assert "backend.current_intraday_session" in source
    assert "backend.daily_ledger_relation" in source
    assert "MARKET_CLOSED_WEEKEND" in source
    assert "STALE_PRIOR_SESSION" in source
    assert "Last Trading Session" in source
    assert "Next Trading Session" in source
    assert "Market Closed / Weekend or Non-Trading Day" in source
    assert "No current session intraday" in source
    assert "Pending today" not in source
    assert '"Current Trading Date"' not in source
    assert "Portfolio Daily Date" in source
    assert "Latest Delayed Price As-Of" in source


def test_phase2c_allocation_dashboard_waiting_and_applied_state_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    smoke = Path("scripts/verify_strategy_factory_operator_view.py").read_text(encoding="utf-8")

    assert "allocationBookedTransactionCost" in source
    assert "allocationCombinedDynamicSummary" in source
    assert "APPROVED_WAITING_EFFECTIVE_DATE" in source
    assert "APPLIED_PAPER" in source
    assert "$0 booked until effective date" in source
    assert "Plan Applied / Paper Effective" in source
    assert "Booked Transaction Cost" in source
    assert "active-unallocated rows now paper-weighted" in source
    assert "Combined updated dynamically" in source
    assert "No Live/Brokerage Orders" in source
    assert "no fake NAV/P&L rewrite" in source
    assert "phase2c-applied-state-readiness" in smoke


def test_phase2c_dashboard_contract_is_not_production_hardcoded() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    phase2c_slice = source[source.find("function allocationLatestAppliedEvent") : source.find("function workflowCommandDiagram")]

    assert "approved-rebalance-bc14d4b7801a" not in phase2c_slice
    assert "#000019" not in phase2c_slice
    assert "#000020" not in phase2c_slice
    assert "Copper Equity Proxy Trend" not in phase2c_slice
    assert "U.S. Stock Low Vol Defensive 63D Top 20" not in phase2c_slice
    assert "2026-06-29" not in phase2c_slice
    assert "ordinary_strategy_count:summary.ordinary_strategy_count??ordinaryActiveRows(c).length" in phase2c_slice


def test_phase3a_monthly_auto_proposal_dashboard_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    smoke = Path("scripts/verify_strategy_factory_operator_view.py").read_text(encoding="utf-8")

    assert "allocationGenerateMonthlyProposal" in source
    assert "allocationReviewMonthlyProposal" in source
    assert "/api/paper-rebalance/monthly-proposal" in source
    assert "MONTHLY_PROPOSAL_READY" in source
    assert "NOT_APPROVED" in source
    assert "Monthly Auto Proposal" in source
    assert "Review Monthly Proposal" in source
    assert "No NAV/P&amp;L Impact Yet" in source
    assert "No Live/Brokerage Orders" in source
    assert "phase3a-monthly-auto-proposal" in smoke


def test_phase3a_monthly_auto_proposal_dashboard_is_not_production_hardcoded() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    phase3a_slice = source[source.find("function allocationLatestMonthlyProposal") : source.find("function workflowCommandDiagram")]

    assert "Copper Equity Proxy Trend" not in phase3a_slice
    assert "U.S. Stock Low Vol Defensive 63D Top 20" not in phase3a_slice
    assert "COPX" not in phase3a_slice
    assert "XME" not in phase3a_slice
    assert "#000019" not in phase3a_slice
    assert "#000020" not in phase3a_slice
    assert "2026-06-29" not in phase3a_slice


def test_dashboard_phase2a_command_center_overflow_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = Path("dashboard/foundation.css").read_text(encoding="utf-8")
    smoke = Path("scripts/verify_strategy_factory_operator_view.py").read_text(encoding="utf-8")

    assert "commandTruncate" in source
    assert "commandSmall" in source
    assert "commandTitle" in source
    assert "overflow-safe-card" in source
    assert "command-performance-table" in source
    assert "command-rebalance-table" in source
    assert "command-overflow-safe" in source
    assert "title=" in source[source.rfind("function allocation(c)") :]
    assert ".text-truncate" in css
    assert ".mono-truncate" in css
    assert ".table-cell-truncate" in css
    assert ".two-line-clamp" in css
    assert ".overflow-safe-card" in css
    assert ".command-performance-table" in css
    assert ".command-rebalance-table" in css
    assert ".cmd-rebalance .allocation-decision-row" in css
    assert ".style-row" in css
    assert "phase2a-command-center-overflow-fix" in smoke
    assert "command-center horizontal overflow" in smoke
    assert "child outside row" in smoke


def test_dashboard_operator_view_styled_evidence_and_provenance_contract() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "factoryStyledReportViewer" in source
    assert "factoryDateRangeLabel" in source
    assert "start&&end" in source
    assert "\\u2014 proxy-only evidence and robustness/risk limitations prevent Candidate admission." in source
    assert "factorySelectedVariantWorkspace" in source
    assert "factorySummaryTab" in source
    assert "factoryBacktestTab" in source
    assert "factoryMlTab" in source
    assert "factoryRobustnessTab" in source
    assert "factoryProvenanceTab" in source
    assert "Field unavailable in artifact" in source
    assert "Feature importance top 5" in source
    assert "Leakage check" in source
    assert "Blocked models/reasons" in source
    assert "ML diagnostics are mixed/weak; not sufficient for Candidate." in source
    assert "Robustness is WATCH, so Candidate admission remains blocked." in source
    assert "Click View Evidence to load selected variant evidence." in source
    assert "data-factory-workspace-tab" in source
    assert 'state.selectedFactoryWorkspaceTab="Evidence"' in source
    assert "Executive Summary" in source
    assert "ML Diagnostics" in source
    assert "Final Decision" in source
    assert "Raw markdown" in source
    assert "Missing Evidence" in source
    assert "Metrics source artifact" in source
    assert "ML source artifact" in source
    assert "Robustness source artifact" in source
    assert "Evidence source artifact" in source
    assert "Ranking source artifact" in source
    assert "Candidate decision source artifact" in source
    assert "Charts unavailable: missing artifact" in source


def test_strategy_factory_variant_evidence_endpoint_returns_markdown(tmp_path: Path) -> None:
    _write_review_fixture(tmp_path)
    variant_id = "COPPER_CPER_MOMENTUM_21_63_V1"

    class TmpRootHandler(WorkstationHandler):
        server_root = tmp_path

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    server = ThreadingHTTPServer(("127.0.0.1", port), TmpRootHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/api/strategy-factory/variants/{variant_id}/evidence?run_id={RUN_ID}"
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
        assert response.status == 200
        assert "text/markdown" in content_type
        assert f"# Evidence {variant_id}" in body
    finally:
        server.shutdown()


def test_dashboard_operator_actions_are_inline_and_non_hash() -> None:
    source = Path("dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "factoryOpenInlineReport" in source
    assert "data-factory-report-url" in source
    assert "Selected Evidence" in source
    assert "factoryMarkdownPreview" in source
    assert "factoryViewportSnapshot" in source
    assert "factoryRestoreViewport" in source
    assert 'href="#factoryReportViewer"' not in source[source.rfind("function factoryCandidatePortfolioPanel") :]
    assert 'href="#factoryCandidateCharts"' not in source[source.rfind("function factoryCandidatePortfolioPanel") :]
