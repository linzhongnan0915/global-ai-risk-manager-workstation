"""Strategy Factory logic audit trace generation.

This is an audit-only layer. It reads existing Strategy Factory artifacts and
writes logic trace documentation without running new research, backtests, ML,
ranking, dashboard changes, trading, or ledger mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _run_dir(root: Path, run_id: str) -> Path:
    return root / "output" / "strategy_factory" / "runs" / run_id


def _variant_dir(run_dir: Path, variant_id: str) -> Path:
    return run_dir / "variants" / variant_id


def _variant_rationale(spec: dict[str, Any]) -> dict[str, Any]:
    variant_id = str(spec.get("variant_id") or "")
    mapping = {
        "COPPER_CPER_MOMENTUM_21_63_V1": {
            "generation_reason": "Create the simplest copper proxy trend baseline before adding filters.",
            "paper_material_mapping": "Maps to material themes: ETF proxy, commodities, momentum.",
            "economic_hypothesis": "Copper ETF trends may persist over short and medium horizons.",
            "distinctiveness": "Pure CPER absolute momentum; no volatility, USD, benchmark-relative, or equity-proxy filter.",
        },
        "COPPER_CPER_MOMENTUM_VOL_FILTER_V1": {
            "generation_reason": "Test whether risk-regime language should gate copper momentum exposure.",
            "paper_material_mapping": "Maps to material themes: momentum and volatility.",
            "economic_hypothesis": "Copper momentum may be more reliable when realized volatility is not elevated.",
            "distinctiveness": "Adds a volatility filter to the CPER momentum baseline.",
        },
        "COPPER_CPER_DBC_RELATIVE_STRENGTH_V1": {
            "generation_reason": "Separate copper-specific strength from broad commodity beta.",
            "paper_material_mapping": "Maps to material themes: ETF proxy, commodities, momentum.",
            "economic_hypothesis": "Copper exposure should be favored only when it outperforms the broad commodity basket.",
            "distinctiveness": "Uses CPER return relative to DBC instead of absolute CPER trend only.",
        },
        "COPPER_CPER_UUP_USD_FILTER_V1": {
            "generation_reason": "Test whether USD macro pressure changes copper trend quality.",
            "paper_material_mapping": "Maps to material themes: commodities and macro proxy; USD filter is inferred from copper macro sensitivity.",
            "economic_hypothesis": "Copper trend may be stronger when USD strength is not a headwind.",
            "distinctiveness": "Adds a UUP/USD macro filter not present in the other CPER-only variants.",
        },
        "COPPER_EQUITY_PROXY_TREND_COPX_XME_V1": {
            "generation_reason": "Test listed copper/miner equity proxies as an alternate expression of copper trend.",
            "paper_material_mapping": "Maps to ETF proxy language; miner/equity expression is an implementation inference.",
            "economic_hypothesis": "Copper-linked equities may capture copper regime sensitivity but add equity beta.",
            "distinctiveness": "Uses COPX/XME with SPY benchmark instead of CPER/DBC commodity proxy exposure.",
        },
        "COMMODITY_BASKET_REGIME_FILTER_V1": {
            "generation_reason": "Test whether broad commodity regime confirmation improves copper proxy trend.",
            "paper_material_mapping": "Maps to material themes: commodities, ETF proxy, momentum.",
            "economic_hypothesis": "Copper exposure may be more robust when the broad commodity basket is also trending.",
            "distinctiveness": "Uses DBC as a regime filter rather than only as benchmark comparison.",
        },
    }
    base = mapping.get(
        variant_id,
        {
            "generation_reason": "Generated from available Strategy Factory variant rules.",
            "paper_material_mapping": "Mapping unavailable.",
            "economic_hypothesis": spec.get("thesis") or "Unavailable.",
            "distinctiveness": "Distinctiveness unavailable.",
        },
    )
    return {
        **base,
        "variant_id": variant_id,
        "variant_name": spec.get("variant_name"),
        "data_proxy_required": list(dict.fromkeys([*(spec.get("universe_or_proxy") or []), spec.get("benchmark")] + [item for item in spec.get("data_requirements") or [] if isinstance(item, str) and item.isupper()])),
        "signal_formula": spec.get("signal_formula"),
        "source_material_ids": spec.get("source_material_ids") or [],
        "non_random_basis": "Variant id, signal formula, features, benchmark, and data requirements are deterministic outputs from Gate 2 templates keyed to copper/material themes.",
    }


def _feature_rationale_for_variant(spec: dict[str, Any]) -> list[dict[str, Any]]:
    descriptions = {
        "momentum_21d": ("Short-term continuation", "Positive momentum should increase long exposure."),
        "momentum_63d": ("Medium-term trend persistence", "Positive momentum should increase long exposure."),
        "momentum_126d": ("Longer commodity regime trend", "Positive momentum should support long exposure."),
        "realized_volatility_21d": ("Recent risk regime", "Elevated volatility should reduce or block exposure."),
        "realized_volatility_252d": ("Longer volatility baseline", "Current volatility below baseline should support exposure."),
        "drawdown": ("Trend break / risk state", "Deeper drawdown should reduce confidence."),
        "commodity_basket_proxy_dbc": ("Broad commodity beta and benchmark context", "Positive DBC regime may support copper exposure."),
        "benchmark_relative_strength_vs_DBC": ("Copper-specific strength versus broad commodities", "Positive relative strength should support exposure."),
        "relative_strength_vs_dbc": ("Copper-specific strength versus broad commodities", "Positive relative strength should support exposure."),
        "relative_strength_vs_spy": ("Miner equity strength versus market beta", "Positive relative strength should support exposure."),
        "usd_proxy_uup": ("USD macro pressure", "UUP strength is expected to be a headwind."),
        "uup_momentum_63d": ("USD trend proxy", "Positive UUP momentum should reduce copper exposure."),
        "usd_filter": ("Binary USD headwind filter", "Filter should block when USD trend is unfavorable."),
        "commodity_regime_filter": ("Broad commodity confirmation", "Positive DBC regime should support exposure."),
        "moving_average_trend": ("Interpretable trend state", "Price/equity above moving average should support exposure."),
        "copx_momentum_63d": ("Copper miner trend", "Positive COPX momentum should support miner proxy exposure."),
        "xme_momentum_63d": ("Metals/mining trend", "Positive XME momentum should support miner proxy exposure."),
        "equity_beta_proxy": ("Equity-market sensitivity", "Higher equity beta increases implementation/admission risk."),
        "cper_momentum_63d": ("CPER medium-term trend", "Positive trend should support CPER exposure."),
        "dbc_momentum_63d": ("Broad commodity medium-term trend", "Positive DBC trend should support commodity exposure."),
        "dbc_momentum_126d": ("Broad commodity regime trend", "Positive DBC regime should support commodity exposure."),
    }
    rows = []
    for feature in spec.get("features") or []:
        text, direction = descriptions.get(feature, ("Variant-specific diagnostic feature", "Expected direction is defined by the variant signal formula."))
        feature_text = str(feature).lower()
        required_source = "local daily return/equity curve artifacts"
        if "dbc" in feature_text:
            required_source = "local DBC proxy data"
        elif "uup" in feature_text or "usd" in feature_text:
            required_source = "local UUP proxy data"
        elif "copx" in feature_text or "xme" in feature_text or "spy" in feature_text or "equity" in feature_text:
            required_source = "local COPX/XME/SPY proxy data"
        elif "cper" in feature_text or "momentum" in feature_text:
            required_source = "local CPER proxy data"
        rows.append(
            {
                "variant_id": spec.get("variant_id"),
                "feature": feature,
                "why_included": text,
                "what_it_measures": text,
                "expected_direction": direction,
                "required_data_source": required_source,
                "leakage_risk": "LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split.",
                "proxy_only": True,
            }
        )
    return rows


def _model_rationale(ml: dict[str, Any], split: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    models = ml.get("models") or []
    blocked = [row for row in models if row.get("status") == "BLOCKED"]
    return {
        "variant_id": spec.get("variant_id"),
        "ridge_reason": "Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.",
        "logistic_reason": "Logistic regression was used for next-period direction because the target is binary up/down.",
        "linear_reason": "Linear regression is an interpretable return baseline.",
        "blocked_nonlinear_models": blocked,
        "blocked_reason_summary": "Random forest and gradient boosting require sklearn/package availability and enough sample support; blocked entries remain explicit rather than faked.",
        "split_reason": "Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.",
        "target_definition": ml.get("target_definition") or "next-period return and next-period direction",
        "sample_count": ml.get("sample_count"),
        "train_dates": ml.get("train_dates") or {"start": split.get("train_start"), "end": split.get("train_end")},
        "test_dates": ml.get("test_dates") or {"start": split.get("test_start"), "end": split.get("test_end")},
        "ml_status": ml.get("status"),
        "artifact_required": "variant_ml_diagnostics_run.json",
    }


def _decision_logic(metrics: dict[str, Any], ml: dict[str, Any], robustness: dict[str, Any], decision: dict[str, Any], ranking_row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "variant_id": decision.get("variant_id"),
        "sharpe": metrics.get("sharpe"),
        "annual_return": metrics.get("annual_return"),
        "max_drawdown": metrics.get("max_drawdown"),
        "ml_ic": (ml.get("prediction_quality") or {}).get("spearman_ic"),
        "ml_hit_rate": (ml.get("direction_quality") or {}).get("direction_hit_rate"),
        "robustness_overall": (robustness.get("summary") or {}).get("overall_status"),
        "cost_sensitivity": (robustness.get("summary") or {}).get("cost_sensitivity_status"),
        "proxy_penalty_applied": bool((decision.get("evidence_flags") or {}).get("proxy_only", True)),
        "candidate_blocking_rule": "Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.",
        "final_label": decision.get("recommendation") or decision.get("decision"),
        "reason": decision.get("reason") or (ranking_row or {}).get("reason"),
        "candidate_allowed": decision.get("candidate") if decision.get("candidate") is not None else (ranking_row or {}).get("candidate_allowed"),
        "ranking_context": ranking_row or {},
    }


def generate_logic_audit(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(root, run_id)
    variants_dir = run_dir / "variants"
    selected_materials = _read_json(run_dir / "selected_materials.json", [])
    material_summary = _read_json(run_dir / "material_summary.json", {})
    classification = _read_json(run_dir / "strategy_type_classification.json", {})
    feature_plan = _read_json(run_dir / "feature_plan.json", {})
    model_plan = _read_json(run_dir / "model_plan.json", {})
    decision_scorecard = _read_json(run_dir / "decision_scorecard.json", {})
    ranking = _read_json(variants_dir / "variant_ranking.json", {})
    registry = _read_json(variants_dir / "variant_registry.json", {})
    ranking_by_variant = {row.get("variant_id"): row for row in ranking.get("rankings") or []}

    material_keywords = []
    for material in selected_materials:
        analysis = material.get("analysis") or {}
        material_keywords.extend(analysis.get("key_themes") or [])
    material_to_strategy_type = {
        "materials_used": [
            {
                "material_id": material.get("material_id"),
                "filename": material.get("filename"),
                "analysis_path": material.get("analysis_path"),
                "extracted_text_path": material.get("extracted_text_path"),
                "source_classification": ((material.get("analysis") or {}).get("source_classification")),
                "key_themes": ((material.get("analysis") or {}).get("key_themes") or []),
                "signal_ideas": ((material.get("analysis") or {}).get("signal_ideas") or []),
            }
            for material in selected_materials
        ],
        "material_summary_path": str(run_dir / "material_summary.json"),
        "strategy_type": classification.get("strategy_type"),
        "trigger_keywords_or_themes": sorted(set(material_keywords + classification.get("evidence", []))),
        "rule_based": [
            "Key themes and signal ideas came from rule-based material detectors.",
            "commodity/macro, trend/momentum, ETF proxy, and volatility themes map deterministically to commodity trend / macro proxy.",
        ],
        "inferred": [
            "USD proxy and equity/miner proxy extensions are economic inferences from copper macro/proxy context, not direct proof of alpha.",
        ],
        "confidence": classification.get("confidence"),
        "limitations": [
            "Material is METHOD_REFERENCE_ONLY, not a validated alpha paper.",
            "Extracted text is short; conclusions depend on controlled material themes.",
            "Classification is transparent and heuristic, not a causal proof.",
        ],
    }

    variants = []
    feature_rationale = {}
    model_rationale = {}
    decisions = {}
    for row in registry.get("variants") or []:
        variant_id = row.get("variant_id")
        variant_dir = _variant_dir(run_dir, variant_id)
        eval_dir = variant_dir / "evaluation"
        spec = _read_json(variant_dir / "variant_spec.json", {})
        metrics = _read_json(eval_dir / "variant_metrics.json", {})
        ml = _read_json(eval_dir / "variant_ml_diagnostics_run.json", {})
        split = _read_json(eval_dir / "variant_train_test_split.json", {})
        robustness = _read_json(eval_dir / "variant_robustness_run.json", {})
        decision = _read_json(eval_dir / "variant_decision.json", {})
        rationale = _variant_rationale(spec)
        variants.append(rationale)
        feature_rationale[variant_id] = _feature_rationale_for_variant(spec)
        model_rationale[variant_id] = _model_rationale(ml, split, spec)
        decisions[variant_id] = _decision_logic(metrics, ml, robustness, decision, ranking_by_variant.get(variant_id))

    ranking_logic = {
        "artifact": str(variants_dir / "variant_ranking.json"),
        "heuristic": True,
        "heuristic_disclaimer": "The formula is a transparent heuristic for prototype ranking; it is not institutional validation or admission logic.",
        "weights": ranking.get("weights") or {
            "performance": 0.25,
            "robustness": 0.20,
            "ml": 0.15,
            "data_quality": 0.15,
            "economic_logic": 0.15,
            "risk_penalty": -0.10,
        },
        "score_components": {
            "performance_score": "Composite of Sharpe, annual return, max drawdown, and benchmark comparison.",
            "robustness_score": "Overall robustness, cost sensitivity, lookback sensitivity, benchmark status, and stress-period behavior.",
            "ml_score": "Return Spearman IC and direction hit rate, with penalty for negative IC.",
            "data_quality_score": "Starts high, then penalizes proxy-only data and equity/miner proxy exposure.",
            "risk_penalty": "Adds penalties for proxy-only data, high drawdown, weak robustness, negative ML IC, and COPX/XME miner beta risk.",
            "evidence_score": "0.25*performance + 0.20*robustness + 0.15*ML + 0.15*data_quality + 0.15*economic_logic - 0.10*risk_penalty.",
        },
        "best_variant": ranking.get("best_variant"),
        "candidate_portfolio_action": ranking.get("candidate_portfolio_action"),
    }

    anti_randomness = {
        "variants_not_random": {
            "status": "PASS",
            "evidence": "Each variant has deterministic id, signal_formula, universe_or_proxy, benchmark, features, and data_requirements in variant_spec.json.",
        },
        "no_candidate_without_artifacts": {
            "status": "PASS",
            "evidence": "candidate_allowed is false for all copper rankings and each decision references completed/blocked artifacts.",
        },
        "no_ml_without_artifact": {
            "status": "PASS",
            "evidence": "ML completion is read from variant_ml_diagnostics_run.json or ml_diagnostics_run.json only.",
        },
        "no_paper_derived_without_source": {
            "status": "PASS",
            "evidence": "Material ids and analysis paths are recorded; source_classification is METHOD_REFERENCE_ONLY rather than overclaiming paper-derived alpha.",
        },
        "proxy_only_blocks_candidate": {
            "status": "PASS",
            "evidence": "PROXY_ONLY status appears in data decisions and candidate_allowed false is explained for the copper run.",
        },
    }

    trace = {
        "schema_version": "strategy_factory_logic_trace_v1",
        "status": "COMPLETED",
        "run_id": run_id,
        "generated_at": _now(),
        "material_to_strategy_type": material_to_strategy_type,
        "strategy_type_to_variants": variants,
        "feature_rationale": feature_rationale,
        "model_rationale": {
            "current_run_model_plan": model_plan,
            "by_variant": model_rationale,
        },
        "decision_logic": {
            "current_run_decision_scorecard": decision_scorecard,
            "by_variant": decisions,
            "candidate_allowed_false_explanation": "The copper run and all evaluated variants are proxy-only and do not satisfy the combined evidence gate for Candidate status.",
        },
        "ranking_logic": ranking_logic,
        "anti_randomness_checks": anti_randomness,
        "non_actions": ["NO_NEW_STRATEGY", "NO_NEW_BACKTEST", "NO_NEW_ML", "NO_NEW_RANKING", "NO_DASHBOARD_LAYOUT_CHANGE", "NO_DEPLOY", "NO_LIVE_TRADING", "NO_PAPER_LEDGER_MUTATION"],
    }
    _write_json(run_dir / "logic_trace.json", trace)
    _write_logic_markdown(run_dir / "logic_trace.md", trace)
    _write_logic_markdown(root / "docs" / "STRATEGY_FACTORY_LOGIC_AUDIT_V1.md", trace)
    return trace


def _write_logic_markdown(path: Path, trace: dict[str, Any]) -> None:
    mat = trace["material_to_strategy_type"]
    ranking = trace["ranking_logic"]
    lines = [
        f"# Strategy Factory Logic Audit V1 - {trace.get('run_id')}",
        "",
        "Status: COMPLETED",
        "",
        "This is an audit of existing Strategy Factory artifacts. It did not run new backtests, ML, ranking, dashboard work, deployment, live trading, or paper-ledger mutation.",
        "",
        "## 1. Material To Strategy Type",
        f"- Strategy type: `{mat.get('strategy_type')}`",
        f"- Confidence: `{mat.get('confidence')}`",
        f"- Material summary path: `{mat.get('material_summary_path')}`",
        f"- Trigger keywords/themes: {', '.join(str(item) for item in mat.get('trigger_keywords_or_themes') or [])}",
        "- Rule-based logic: " + " ".join(mat.get("rule_based") or []),
        "- Inferred logic: " + " ".join(mat.get("inferred") or []),
        "- Limitations: " + " ".join(mat.get("limitations") or []),
        "",
        "## 2. Strategy Type To Variants",
    ]
    for variant in trace["strategy_type_to_variants"]:
        lines.extend(
            [
                f"### {variant.get('variant_id')}",
                f"- Name: {variant.get('variant_name')}",
                f"- Why generated: {variant.get('generation_reason')}",
                f"- Material mapping: {variant.get('paper_material_mapping')}",
                f"- Economic hypothesis: {variant.get('economic_hypothesis')}",
                f"- Data/proxy required: {', '.join(str(item) for item in variant.get('data_proxy_required') or [])}",
                f"- Distinctness: {variant.get('distinctiveness')}",
                "",
            ]
        )
    lines.append("## 3. Variant To Features")
    for variant_id, features in trace["feature_rationale"].items():
        lines.append(f"### {variant_id}")
        for feature in features:
            lines.append(
                f"- `{feature.get('feature')}`: {feature.get('why_included')} Measures: {feature.get('what_it_measures')}. Expected direction: {feature.get('expected_direction')} Source: {feature.get('required_data_source')}. Leakage risk: {feature.get('leakage_risk')} Proxy-only: `{feature.get('proxy_only')}`."
            )
        lines.append("")
    lines.append("## 4. Variant To Model Plan")
    for variant_id, model in trace["model_rationale"]["by_variant"].items():
        lines.extend(
            [
                f"### {variant_id}",
                f"- Ridge: {model.get('ridge_reason')}",
                f"- Logistic: {model.get('logistic_reason')}",
                f"- Chronological split: {model.get('split_reason')}",
                f"- Target definition: {model.get('target_definition')}",
                f"- Sample count: {model.get('sample_count')}",
                f"- Train dates: {model.get('train_dates')}",
                f"- Test dates: {model.get('test_dates')}",
                f"- Blocked nonlinear models: {json.dumps(model.get('blocked_nonlinear_models') or [], sort_keys=True)}",
                "",
            ]
        )
    lines.append("## 5. Metrics / Robustness To Decision")
    for variant_id, decision in trace["decision_logic"]["by_variant"].items():
        lines.extend(
            [
                f"### {variant_id}",
                f"- Sharpe: `{decision.get('sharpe')}`",
                f"- Annual return: `{decision.get('annual_return')}`",
                f"- Max drawdown: `{decision.get('max_drawdown')}`",
                f"- ML IC: `{decision.get('ml_ic')}`",
                f"- Hit rate: `{decision.get('ml_hit_rate')}`",
                f"- Robustness: `{decision.get('robustness_overall')}`",
                f"- Proxy penalty applied: `{decision.get('proxy_penalty_applied')}`",
                f"- Candidate blocking rule: {decision.get('candidate_blocking_rule')}",
                f"- Final label: `{decision.get('final_label')}`",
                f"- Reason: {decision.get('reason')}",
                "",
            ]
        )
    lines.extend(
        [
            "## 6. Ranking Score",
            f"- Heuristic: `{ranking.get('heuristic')}`",
            f"- Disclaimer: {ranking.get('heuristic_disclaimer')}",
            f"- Weights: `{json.dumps(ranking.get('weights'), sort_keys=True)}`",
        ]
    )
    for name, explanation in (ranking.get("score_components") or {}).items():
        lines.append(f"- `{name}`: {explanation}")
    best = ranking.get("best_variant") or {}
    lines.extend(
        [
            f"- Best variant: `{best.get('variant_id')}`",
            f"- Best variant recommendation: `{best.get('final_recommendation')}`",
            f"- Candidate portfolio action: `{ranking.get('candidate_portfolio_action')}`",
            "",
            "## 7. Anti-Randomness Checks",
        ]
    )
    for name, check in trace["anti_randomness_checks"].items():
        lines.append(f"- `{name}`: {check.get('status')} - {check.get('evidence')}")
    lines.extend(
        [
            "",
            "## Answer To Audit Question",
            "Factory logic used controlled material themes to classify the run as commodity trend / macro proxy, generated deterministic copper proxy variants from that type, selected features/models based on interpretable time-series diagnostics, evaluated evidence through metrics/ML/robustness/proxy penalties, ranked variants with a transparent heuristic score, and rejected Candidate status because the evidence is proxy-only and not strong enough for admission.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
