from __future__ import annotations

import json
from pathlib import Path

from src.strategies.strategy_factory_logic_audit import generate_logic_audit


RUN_ID = "SF_RUN_LOGIC_AUDIT_FIXTURE"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_fixture_run(root: Path) -> None:
    run_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID
    variants_dir = run_dir / "variants"
    material_id = "MAT_CONTROLLED_COPPER_FIXTURE"
    selected_material = {
        "material_id": material_id,
        "filename": "controlled_copper_strategy_material.md",
        "analysis_path": "material_analysis.json",
        "extracted_text_path": "material_text.txt",
        "analysis": {
            "source_classification": "METHOD_REFERENCE_ONLY",
            "key_themes": ["ETF proxy", "commodities", "momentum", "volatility"],
            "signal_ideas": ["Rule-based detector found commodities language."],
        },
    }
    _write_json(run_dir / "selected_materials.json", [selected_material])
    _write_json(run_dir / "material_summary.json", {"materials": [selected_material]})
    _write_json(
        run_dir / "strategy_type_classification.json",
        {
            "strategy_type": "commodity trend / macro proxy",
            "confidence": "HIGH",
            "evidence": ["commodity/macro keywords found", "trend or momentum language found"],
        },
    )
    _write_json(run_dir / "feature_plan.json", {"status": "COMPLETED", "included_features": ["momentum_21d"]})
    _write_json(run_dir / "model_plan.json", {"status": "COMPLETED", "split_method": "chronological_no_shuffle"})
    _write_json(run_dir / "decision_scorecard.json", {"candidate_allowed": False, "recommendation": "Watch"})
    variant_ids = [
        "COPPER_CPER_MOMENTUM_21_63_V1",
        "COPPER_CPER_MOMENTUM_VOL_FILTER_V1",
    ]
    registry_rows = []
    ranking_rows = []
    for rank, variant_id in enumerate(variant_ids, start=1):
        variant_dir = variants_dir / variant_id
        eval_dir = variant_dir / "evaluation"
        spec = {
            "variant_id": variant_id,
            "variant_name": variant_id.replace("_", " ").title(),
            "source_run_id": RUN_ID,
            "source_material_ids": [material_id],
            "signal_formula": "Long CPER when momentum is positive.",
            "universe_or_proxy": ["CPER"],
            "benchmark": "DBC",
            "features": ["momentum_21d", "momentum_63d", "commodity_basket_proxy_dbc"],
            "data_requirements": ["CPER", "DBC"],
            "testability_status": "PROXY_ONLY",
        }
        _write_json(variant_dir / "variant_spec.json", spec)
        _write_json(eval_dir / "variant_metrics.json", {"status": "COMPLETED", "sharpe": 0.2, "annual_return": 0.02, "max_drawdown": -0.2, "prototype_proxy_only": True})
        _write_json(
            eval_dir / "variant_ml_diagnostics_run.json",
            {
                "status": "COMPLETED",
                "models": [{"model": "random_forest", "status": "BLOCKED", "reason": "sklearn unavailable"}],
                "target_definition": "next_period_net_return",
                "sample_count": 200,
                "train_dates": {"start": "2020-01-01", "end": "2021-01-01"},
                "test_dates": {"start": "2021-01-04", "end": "2022-01-01"},
                "prediction_quality": {"spearman_ic": -0.01},
                "direction_quality": {"direction_hit_rate": 0.52},
            },
        )
        _write_json(eval_dir / "variant_train_test_split.json", {"split_method": "chronological_no_shuffle"})
        _write_json(eval_dir / "variant_robustness_run.json", {"status": "COMPLETED", "summary": {"overall_status": "WATCH", "cost_sensitivity_status": "PASS"}})
        _write_json(eval_dir / "variant_decision.json", {"variant_id": variant_id, "recommendation": "Modify", "candidate": False, "reason": "Proxy-only data blocks Candidate."})
        registry_rows.append({"variant_id": variant_id, "variant_name": spec["variant_name"]})
        ranking_rows.append(
            {
                "rank": rank,
                "variant_id": variant_id,
                "variant_name": spec["variant_name"],
                "evidence_score": 40.0,
                "performance_score": 30.0,
                "robustness_score": 50.0,
                "ml_score": 45.0,
                "data_quality_score": 65.0,
                "risk_penalty": 32.0,
                "final_recommendation": "Modify",
                "candidate_allowed": False,
                "reason": "proxy-only data prevents Candidate status.",
            }
        )
    _write_json(variants_dir / "variant_registry.json", {"variants": registry_rows})
    _write_json(
        variants_dir / "variant_ranking.json",
        {
            "weights": {"performance": 0.25, "robustness": 0.20, "ml": 0.15, "data_quality": 0.15, "economic_logic": 0.15, "risk_penalty": -0.10},
            "rankings": ranking_rows,
            "best_variant": ranking_rows[0],
            "candidate_portfolio_action": "NONE",
        },
    )


def test_logic_audit_trace_documents_reasoning_and_candidate_block(tmp_path: Path) -> None:
    _write_fixture_run(tmp_path)

    trace = generate_logic_audit(tmp_path, RUN_ID)

    run_dir = tmp_path / "output" / "strategy_factory" / "runs" / RUN_ID
    assert (run_dir / "logic_trace.json").is_file()
    assert (run_dir / "logic_trace.md").is_file()
    assert (tmp_path / "docs" / "STRATEGY_FACTORY_LOGIC_AUDIT_V1.md").is_file()
    for key in [
        "material_to_strategy_type",
        "strategy_type_to_variants",
        "feature_rationale",
        "model_rationale",
        "decision_logic",
        "ranking_logic",
    ]:
        assert key in trace
    assert all(row["generation_reason"] for row in trace["strategy_type_to_variants"])
    assert "performance_score" in trace["ranking_logic"]["score_components"]
    assert "evidence_score" in trace["ranking_logic"]["score_components"]
    assert "candidate_allowed_false_explanation" in trace["decision_logic"]
    assert "proxy-only" in trace["decision_logic"]["candidate_allowed_false_explanation"]
    assert trace["anti_randomness_checks"]["proxy_only_blocks_candidate"]["status"] == "PASS"
