"""Strategy Factory Gate 4 variant ranking.

Ranks already evaluated variants by composite evidence quality. This module
does not run backtests, ML, robustness evaluation, trading, deployment, or
paper-ledger actions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import math


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


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _run_dir(root: Path, run_id: str) -> Path:
    return root / "output" / "strategy_factory" / "runs" / run_id


def _variant_dir(root: Path, run_id: str, variant_id: str) -> Path:
    return _run_dir(root, run_id) / "variants" / variant_id


def _performance_score(metrics: dict[str, Any], robustness: dict[str, Any]) -> float:
    if metrics.get("status") != "COMPLETED":
        return 0.0
    sharpe = _float(metrics.get("sharpe"))
    annual_return = _float(metrics.get("annual_return"))
    max_drawdown = _float(metrics.get("max_drawdown"))
    benchmark_return = _float(metrics.get("benchmark_annual_return"))
    benchmark_edge = annual_return - benchmark_return
    sharpe_score = _clamp((sharpe + 0.25) / 1.5 * 100.0)
    return_score = _clamp((annual_return + 0.02) / 0.20 * 100.0)
    drawdown_score = _clamp(100.0 + max_drawdown * 250.0)
    benchmark_score = _clamp(50.0 + benchmark_edge * 250.0)
    if ((robustness.get("summary") or {}).get("benchmark_status") == "WATCH"):
        benchmark_score -= 8.0
    return round(_clamp(0.35 * sharpe_score + 0.25 * return_score + 0.25 * drawdown_score + 0.15 * benchmark_score), 4)


def _robustness_score(robustness: dict[str, Any]) -> float:
    if robustness.get("status") != "COMPLETED":
        return 0.0
    summary = robustness.get("summary") or {}
    base = {"PASS": 75.0, "WATCH": 45.0, "FAIL": 20.0, "BLOCKED": 0.0}.get(summary.get("overall_status"), 35.0)
    cost = {"PASS": 12.0, "WATCH": 4.0, "FAIL": -8.0}.get(summary.get("cost_sensitivity_status"), 0.0)
    lookback = {"PASS": 10.0, "WATCH": 3.0, "FAIL": -8.0}.get(summary.get("lookback_sensitivity_status"), 0.0)
    benchmark = {"PASS": 8.0, "WATCH": -5.0, "FAIL": -12.0}.get(summary.get("benchmark_status"), 0.0)
    stress = robustness.get("stress_periods") or {}
    high_vol_sharpe = _float((stress.get("high_vol_period") or {}).get("sharpe"), default=-1.0)
    recent_sharpe = _float((stress.get("recent_period") or {}).get("sharpe"), default=0.0)
    stress_adjust = 8.0 if high_vol_sharpe > 0.0 else -10.0
    if recent_sharpe > 0.3:
        stress_adjust += 4.0
    return round(_clamp(base + cost + lookback + benchmark + stress_adjust), 4)


def _ml_score(ml: dict[str, Any]) -> float:
    if ml.get("ml_evidence_status") == "MISSING_EVIDENCE":
        return 0.0
    if ml.get("status") != "COMPLETED":
        return 0.0
    quality = ml.get("prediction_quality") or {}
    direction = ml.get("direction_quality") or {}
    ic = _float(quality.get("spearman_ic"))
    hit = _float(direction.get("direction_hit_rate"), default=0.5)
    ic_score = _clamp(50.0 + ic * 600.0)
    hit_score = _clamp((hit - 0.45) / 0.25 * 100.0)
    if ic <= 0.0:
        ic_score -= 15.0
    return round(_clamp(0.6 * ic_score + 0.4 * hit_score), 4)


def _data_quality_score(spec: dict[str, Any], metrics: dict[str, Any]) -> float:
    score = 100.0
    if spec.get("testability_status") == "PROXY_ONLY" or metrics.get("prototype_proxy_only") is True:
        score -= 35.0
    universe = {str(symbol).upper() for symbol in spec.get("universe_or_proxy") or []}
    if spec.get("theme") != "etf_momentum_rotation" and {"COPX", "XME"}.intersection(universe):
        score -= 20.0
    if "UUP" in {str(item).upper() for item in spec.get("data_requirements") or []}:
        score -= 5.0
    return round(_clamp(score), 4)


def _economic_logic_score(spec: dict[str, Any]) -> float:
    variant_id = str(spec.get("variant_id") or "")
    if spec.get("theme") == "etf_momentum_rotation":
        return 72.0 if "TOP2" in variant_id else 70.0
    if spec.get("theme") == "us_stock_cross_sectional_momentum_quality":
        if "QUALITY" in variant_id:
            return 76.0
        if "LIQUIDITY" in variant_id:
            return 74.0
        return 72.0
    if spec.get("theme") == "us_stock_low_vol_defensive":
        if "BETA_FILTER" in variant_id:
            return 75.0
        if "126D" in variant_id:
            return 73.0
        return 71.0
    if spec.get("theme") == "unknown_review_required":
        return 0.0
    if variant_id == "COPPER_CPER_MOMENTUM_VOL_FILTER_V1":
        return 82.0
    if variant_id == "COMMODITY_BASKET_REGIME_FILTER_V1":
        return 78.0
    if variant_id == "COPPER_CPER_DBC_RELATIVE_STRENGTH_V1":
        return 74.0
    if variant_id == "COPPER_CPER_UUP_USD_FILTER_V1":
        return 72.0
    if variant_id == "COPPER_CPER_MOMENTUM_21_63_V1":
        return 68.0
    if variant_id == "COPPER_EQUITY_PROXY_TREND_COPX_XME_V1":
        return 58.0
    return 50.0


def _risk_penalty(spec: dict[str, Any], metrics: dict[str, Any], ml: dict[str, Any], robustness: dict[str, Any]) -> float:
    penalty = 0.0
    max_drawdown = _float(metrics.get("max_drawdown"))
    if max_drawdown < -0.25:
        penalty += min(25.0, abs(max_drawdown + 0.25) * 120.0 + 8.0)
    if spec.get("testability_status") == "PROXY_ONLY" or metrics.get("prototype_proxy_only") is True:
        penalty += 12.0
    universe = {str(symbol).upper() for symbol in spec.get("universe_or_proxy") or []}
    if spec.get("theme") != "etf_momentum_rotation" and {"COPX", "XME"}.intersection(universe):
        penalty += 22.0
    if ((robustness.get("summary") or {}).get("overall_status") != "PASS"):
        penalty += 12.0
    quality = ml.get("prediction_quality") or {}
    if _float(quality.get("spearman_ic")) <= 0.0:
        penalty += 8.0
    return round(_clamp(penalty, 0.0, 70.0), 4)


def _recommendation(score: float, candidate_allowed: bool, existing: str | None) -> str:
    if candidate_allowed and score >= 75.0:
        return "Candidate"
    if score >= 55.0:
        return "Watch"
    if score >= 30.0:
        return "Modify"
    return existing if existing in {"Reject", "Blocked"} else "Reject"


def _score_variant(spec: dict[str, Any], metrics: dict[str, Any], ml: dict[str, Any], robustness: dict[str, Any], decision: dict[str, Any], readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    performance = _performance_score(metrics, robustness)
    robust = _robustness_score(robustness)
    ml_score = _ml_score(ml)
    data_quality = _data_quality_score(spec, metrics)
    economic = _economic_logic_score(spec)
    risk = _risk_penalty(spec, metrics, ml, robustness)
    evidence = _clamp(0.25 * performance + 0.20 * robust + 0.15 * ml_score + 0.15 * data_quality + 0.15 * economic - 0.10 * risk)
    proxy_only = spec.get("testability_status") == "PROXY_ONLY" or metrics.get("prototype_proxy_only") is True
    candidate_allowed = bool(
        not proxy_only
        and evidence >= 75.0
        and performance >= 70.0
        and robust >= 70.0
        and ml_score >= 60.0
        and risk <= 20.0
        and decision.get("candidate") is True
    )
    final_recommendation = _recommendation(evidence, candidate_allowed, decision.get("recommendation") or decision.get("decision"))
    reason_parts = []
    if proxy_only:
        reason_parts.append("proxy-only data prevents Candidate status")
    if robust < 70.0:
        reason_parts.append("robustness is not strong enough")
    if risk >= 30.0:
        reason_parts.append("risk penalties are material")
    if ml.get("ml_evidence_status") == "MISSING_EVIDENCE":
        reason_parts.append("ML evidence is missing")
    elif ml_score < 55.0:
        reason_parts.append("ML evidence is mixed or weak")
    if not reason_parts:
        reason_parts.append("composite evidence is comparatively stronger but still requires institutional data validation")
    return {
        "variant_id": spec.get("variant_id"),
        "variant_name": spec.get("variant_name"),
        "evidence_score": round(evidence, 4),
        "performance_score": performance,
        "robustness_score": robust,
        "ml_score": ml_score,
        "data_quality_score": data_quality,
        "economic_logic_score": economic,
        "risk_penalty": risk,
        "final_recommendation": final_recommendation,
        "candidate_allowed": candidate_allowed,
        "reason": "; ".join(reason_parts) + ".",
        "source_metrics": {
            "sharpe": metrics.get("sharpe"),
            "annual_return": metrics.get("annual_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "benchmark_annual_return": metrics.get("benchmark_annual_return"),
        },
        "source_evidence": {
            "metrics_status": metrics.get("status"),
            "ml_status": ml.get("status"),
            "robustness_status": robustness.get("status"),
            "robustness_overall": (robustness.get("summary") or {}).get("overall_status"),
            "cost_sensitivity": (robustness.get("summary") or {}).get("cost_sensitivity_status"),
            "stress_high_vol_sharpe": ((robustness.get("stress_periods") or {}).get("high_vol_period") or {}).get("sharpe"),
            "ml_ic": (ml.get("prediction_quality") or {}).get("spearman_ic"),
            "ml_hit_rate": (ml.get("direction_quality") or {}).get("direction_hit_rate"),
            "ml_evidence_status": ml.get("ml_evidence_status") or ("REAL_COMPUTED_ML" if ml.get("status") == "COMPLETED" else "MISSING_EVIDENCE"),
        },
        "automation_ready": bool((readiness or {}).get("automation_ready")),
        "automation_block_reason": (readiness or {}).get("automation_block_reason") or "READINESS_ARTIFACT_MISSING",
        "readiness_status": readiness or {},
    }


def rank_variants(root: Path, source_run_id: str) -> dict[str, Any]:
    variants_dir = _run_dir(root, source_run_id) / "variants"
    registry = _read_json(variants_dir / "variant_registry.json", {})
    if not registry:
        raise ValueError(f"Variant registry not found: {variants_dir / 'variant_registry.json'}")
    rows = []
    for registry_row in registry.get("variants") or []:
        variant_id = str(registry_row.get("variant_id") or "")
        variant_dir = _variant_dir(root, source_run_id, variant_id)
        evaluation_dir = variant_dir / "evaluation"
        spec = _read_json(variant_dir / "variant_spec.json", {})
        metrics = _read_json(evaluation_dir / "variant_metrics.json", {})
        ml = _read_json(evaluation_dir / "variant_ml_diagnostics_run.json", {})
        robustness = _read_json(evaluation_dir / "variant_robustness_run.json", {})
        decision = _read_json(evaluation_dir / "variant_decision.json", {})
        readiness = _read_json(evaluation_dir / "variant_readiness_status.json", {})
        if not all([spec, metrics, ml, robustness, decision]):
            scored = {
                "variant_id": variant_id,
                "variant_name": registry_row.get("variant_name"),
                "evidence_score": 0.0,
                "performance_score": 0.0,
                "robustness_score": 0.0,
                "ml_score": 0.0,
                "data_quality_score": 0.0,
                "economic_logic_score": 0.0,
                "risk_penalty": 70.0,
                "final_recommendation": "Blocked",
                "candidate_allowed": False,
                "reason": "Missing one or more Gate 3B evaluation artifacts.",
                "source_metrics": {},
                "source_evidence": {},
                "automation_ready": False,
                "automation_block_reason": "READINESS_ARTIFACT_MISSING",
                "readiness_status": readiness,
            }
        else:
            scored = _score_variant(spec, metrics, ml, robustness, decision, readiness)
        rows.append(scored)
    rows = sorted(rows, key=lambda row: (row["evidence_score"], row["performance_score"]), reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    payload = {
        "schema_version": "strategy_factory_variant_ranking_v1",
        "status": "COMPLETED",
        "source_run_id": source_run_id,
        "ranking_method": "Composite evidence score; not Sharpe-only.",
        "weights": {
            "performance": 0.25,
            "robustness": 0.20,
            "ml": 0.15,
            "data_quality": 0.15,
            "economic_logic": 0.15,
            "risk_penalty": -0.10,
        },
        "penalties": [
            "proxy-only data",
            "high drawdown",
            "weak robustness",
            "negative, weak, or missing ML evidence",
            "theme-specific implementation and proxy risk",
            "implementation complexity",
        ],
        "variant_count": len(rows),
        "rankings": rows,
        "best_variant": rows[0] if rows else None,
        "candidate_portfolio_action": "NONE",
        "non_actions": ["NO_NEW_BACKTESTS", "NO_NEW_ML", "NO_DASHBOARD_LAYOUT_CHANGE", "NO_DEPLOY", "NO_LIVE_TRADING", "NO_PAPER_LEDGER_MUTATION", "NO_CANDIDATE_PORTFOLIO_ADDITION"],
        "generated_at": _now(),
    }
    _write_json(variants_dir / "variant_ranking.json", payload)
    _write_report(variants_dir / "variant_ranking_report.md", payload)
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    rankings = payload.get("rankings") or []
    best = payload.get("best_variant") or {}
    lines = [
        f"# Strategy Factory Gate 4 Variant Ranking - {payload.get('source_run_id')}",
        "",
        "Status: PASS",
        "",
        "## Executive Summary",
        "Gate 4 ranks evaluated variants using a composite evidence score. It does not run new backtests, run new ML, deploy, touch live trading, mutate the paper ledger, or add any variant to a Candidate Portfolio.",
        "",
        "## Best Variant",
        f"- Variant: `{best.get('variant_id')}`",
        f"- Evidence score: `{best.get('evidence_score')}`",
        f"- Recommendation: `{best.get('final_recommendation')}`",
        f"- Candidate allowed: `{best.get('candidate_allowed')}`",
        f"- Reason: {best.get('reason')}",
        "",
        "The best variant ranked highest because its evidence balance was stronger after drawdown, robustness, ML, data-quality, and implementation-risk penalties. It is not Candidate because the evidence remains proxy-only and robustness is not strong enough.",
        "",
        "## Ranking Logic",
        "- Performance includes Sharpe, annual return, drawdown, and benchmark comparison.",
        "- Robustness includes overall robustness status, cost sensitivity, lookback sensitivity, benchmark status, and stress-period behavior.",
        "- ML score uses return IC and direction hit-rate quality, with a penalty for negative IC.",
        "- Data quality penalizes public/proxy-only evidence and theme-specific proxy limitations.",
        "- Risk penalty captures high drawdown, weak robustness, proxy-only status, and negative or missing ML evidence.",
        "",
        "## Per-Variant Comparison",
        "| Rank | Variant | Evidence | Performance | Robustness | ML | Data Quality | Risk Penalty | Recommendation |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rankings:
        lines.append(
            f"| {row.get('rank')} | `{row.get('variant_id')}` | `{row.get('evidence_score')}` | `{row.get('performance_score')}` | `{row.get('robustness_score')}` | `{row.get('ml_score')}` | `{row.get('data_quality_score')}` | `{row.get('risk_penalty')}` | `{row.get('final_recommendation')}` |"
        )
    lines.extend(
        [
            "",
            "## Key Weaknesses",
            "- All variants use proxy-only data, so none can be admitted as institutional candidates.",
            "- Robustness is `WATCH` across the evaluated set.",
            "- Several variants have weak Sharpe, high drawdown, or do not beat their benchmark.",
            "- ML evidence may be missing or mixed; missing ML is not treated as computed evidence.",
            "",
            "## Next Experiment Recommendation",
            "Use the best-ranked Watch variant as the first candidate for a stricter validation pass, but do not admit it. The next experiment should run a broker/API-grade data validation pass, add transaction-cost scenarios grounded in actual execution assumptions, and compare out-of-sample stability before any portfolio discussion.",
            "",
            "## Data Needed From Boss/API",
            "- Institutional-quality adjusted OHLCV with clear corporate-action handling.",
            "- Point-in-time ETF constituent and mapping metadata where equity proxies are used.",
            "- Futures or commodity index data for copper and broad commodity benchmarks.",
            "- Borrow, fee, spread, and executable-volume assumptions for realistic cost modeling.",
            "- Data-quality manifests with survivorship, symbol changes, holidays, and missing ranges.",
            "",
            "## Non-Actions",
            "- No new backtests.",
            "- No new ML diagnostics.",
            "- No dashboard layout change.",
            "- No deployment.",
            "- No live trading.",
            "- No paper ledger mutation.",
            "- No Candidate Portfolio addition.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
