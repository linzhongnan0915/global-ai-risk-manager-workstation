"""Strategy Factory material lineage and automation-readiness gates.

This module writes evidence about what was generated from a source material and
whether a strategy/variant is ready for automation review. It does not run
automation, mutate portfolios, or fabricate research metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re


THEME_US_STOCK_MOMENTUM_QUALITY = "us_stock_cross_sectional_momentum_quality"
THEME_US_STOCK_LOW_VOL_DEFENSIVE = "us_stock_low_vol_defensive"
THEME_UNKNOWN_REVIEW_REQUIRED = "unknown_review_required"
MISSING_EVIDENCE = "Missing Evidence"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def source_material_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_value(text: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)}\s*:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip().rstrip(".") if match else None


def _bullet_section(text: str, heading: str) -> list[str]:
    match = re.search(rf"^{re.escape(heading)}\s*:\s*(.*?)(?:\n\n|\Z)", text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if not match:
        return []
    body = match.group(1)
    rows = []
    first = body.strip().splitlines()[0].strip() if body.strip() else ""
    if first and not first.startswith("-"):
        rows.append(first.rstrip("."))
    rows.extend(line.strip()[2:].rstrip(".") for line in body.splitlines() if line.strip().startswith("- "))
    return [row for row in rows if row]


def extract_material_spec(material_path: Path) -> dict[str, Any]:
    text = material_path.read_text(encoding="utf-8", errors="replace")
    lower = text.lower()
    if any(token in lower for token in ("low vol", "low-vol", "low volatility", "lower volatility", "defensive", "realized volatility", "beta filter")):
        theme = THEME_US_STOCK_LOW_VOL_DEFENSIVE
    elif any(token in lower for token in ("u.s. stock", "us stock", "u.s. equity", "us equity", "cross-sectional", "quality")):
        theme = THEME_US_STOCK_MOMENTUM_QUALITY
    else:
        theme = THEME_UNKNOWN_REVIEW_REQUIRED
    objective = _line_value(text, "Objective") or MISSING_EVIDENCE
    universe_line = _line_value(text, "Universe") or MISSING_EVIDENCE
    benchmark = _line_value(text, "Benchmark") or MISSING_EVIDENCE
    signal_rows = _bullet_section(text, "Signal")
    portfolio_rows = _bullet_section(text, "Portfolio construction")
    evidence_rows = _bullet_section(text, "Evidence requirements")
    return {
        "schema_version": "strategy_factory_material_extraction_v1",
        "source_material_path": str(material_path),
        "source_material_hash": source_material_hash(material_path),
        "generated_at": now_utc(),
        "generated_from_material": True,
        "theme": theme,
        "strategy_name": (
            "U.S. Stock Momentum + Quality Screen"
            if theme == THEME_US_STOCK_MOMENTUM_QUALITY
            else "U.S. Stock Low Vol Defensive Screen"
            if theme == THEME_US_STOCK_LOW_VOL_DEFENSIVE
            else "Review Required - Unknown Material"
        ),
        "thesis": objective,
        "signal_formula": "; ".join(signal_rows) if signal_rows else MISSING_EVIDENCE,
        "universe": universe_line,
        "benchmark": benchmark,
        "rebalance_frequency": _line_value(text, "Rebalance") or MISSING_EVIDENCE,
        "portfolio_construction": "; ".join(portfolio_rows) if portfolio_rows else MISSING_EVIDENCE,
        "evidence_requirements": evidence_rows,
        "material_character_count": len(text),
    }


def _run_dir(root: Path, run_id: str) -> Path:
    return root / "output" / "strategy_factory" / "runs" / run_id


def write_material_generation_artifacts(root: Path, material_path: Path, run_id: str | None = None) -> dict[str, Any]:
    spec = extract_material_spec(material_path)
    digest = spec["source_material_hash"][:8].upper()
    actual_run_id = run_id or f"SF_RUN_PHASE3C_{digest}"
    run_dir = _run_dir(root, actual_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    material_id = f"MAT_{Path(material_path).stem.upper()}_{digest}"
    selected_material = {
        "material_id": material_id,
        "filename": Path(material_path).name,
        "source_material_path": str(material_path),
        "source_material_hash": spec["source_material_hash"],
        "extraction_status": "Extracted",
        "extracted_character_count": spec["material_character_count"],
        "generated_from_material": True,
        "analysis": {
            "document_summary": spec["thesis"],
            "strategy_concepts": [spec["strategy_name"]],
            "signal_ideas": [spec["signal_formula"]],
            "data_requirements": spec["evidence_requirements"],
            "theme": spec["theme"],
        },
    }
    artifacts = {
        "selected_materials": str(run_dir / "selected_materials.json"),
        "material_metadata": str(run_dir / "material_metadata.json"),
        "material_summary": str(run_dir / "material_summary.json"),
        "research_card": str(run_dir / "research_card.json"),
        "research_card_markdown": str(run_dir / "research_card.md"),
        "test_spec": str(run_dir / "test_spec.md"),
        "evidence_manifest": str(run_dir / "evidence_manifest.json"),
        "readiness_status": str(run_dir / "readiness_status.json"),
    }
    write_json(Path(artifacts["selected_materials"]), [selected_material])
    write_json(Path(artifacts["material_metadata"]), spec)
    write_json(Path(artifacts["material_summary"]), {"schema_version": "strategy_factory_material_summary_v1", "run_id": actual_run_id, "materials": [selected_material], **spec})
    research_card = {"schema_version": "strategy_factory_research_card_v1", "run_id": actual_run_id, **spec}
    write_json(Path(artifacts["research_card"]), research_card)
    Path(artifacts["research_card_markdown"]).write_text(
        "\n".join(
            [
                f"# {spec['strategy_name']}",
                "",
                f"- Theme: {spec['theme']}",
                f"- Generated from material: {spec['generated_from_material']}",
                f"- Source material path: {spec['source_material_path']}",
                f"- Source material hash: {spec['source_material_hash']}",
                f"- Thesis: {spec['thesis']}",
                f"- Signal: {spec['signal_formula']}",
                f"- Universe: {spec['universe']}",
                f"- Benchmark: {spec['benchmark']}",
                f"- Rebalance: {spec['rebalance_frequency']}",
                f"- Portfolio construction: {spec['portfolio_construction']}",
                "",
                "## Evidence Requirements",
                *[f"- {item}" for item in spec["evidence_requirements"]],
            ]
        ),
        encoding="utf-8",
    )
    Path(artifacts["test_spec"]).write_text(
        "\n".join(
            [
                f"# Test Spec - {spec['strategy_name']}",
                "",
                f"theme: {spec['theme']}",
                f"generated_from_material: {str(spec['generated_from_material']).lower()}",
                f"source_material_path: {spec['source_material_path']}",
                f"source_material_hash: {spec['source_material_hash']}",
                f"strategy_name: {spec['strategy_name']}",
                f"thesis: {spec['thesis']}",
                f"signal_formula: {spec['signal_formula']}",
                f"universe: {spec['universe']}",
                f"benchmark: {spec['benchmark']}",
                f"rebalance_frequency: {spec['rebalance_frequency']}",
                f"portfolio_construction: {spec['portfolio_construction']}",
                "",
                "Evidence requirements:",
                *[f"- {item}" for item in spec["evidence_requirements"]],
            ]
        ),
        encoding="utf-8",
    )
    evidence = evidence_manifest(
        spec,
        None,
        None,
        {"status": "MISSING_EVIDENCE", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No variant evidence run has been executed yet."},
        artifacts,
    )
    readiness = automation_readiness(spec, None, None, evidence, artifacts)
    write_json(Path(artifacts["evidence_manifest"]), evidence)
    write_json(Path(artifacts["readiness_status"]), readiness)
    run_manifest = {
        "schema_version": "strategy_factory_run_manifest_v1",
        "run_id": actual_run_id,
        "batch_id": f"BATCH_PHASE3C_{digest}",
        "created_at": now_utc(),
        "status": "MATERIAL_GENERATED",
        "generated_from_material": True,
        "strategy_factory_theme": spec["theme"],
        "selected_material_ids": [material_id],
        "selected_material_names": [Path(material_path).name],
        "selected_material_count": 1,
        "generated_artifacts": artifacts,
        "candidate_output": {
            "strategy_id": f"RUN_SCOPED_CANDIDATE_{actual_run_id}",
            "source_material_ids": [material_id],
            "source_run_id": actual_run_id,
            "prototype_only": True,
        },
    }
    write_json(run_dir / "run_manifest.json", run_manifest)
    return {"ok": True, "run_id": actual_run_id, "run_dir": str(run_dir), "spec": spec, "artifacts": artifacts, "readiness": readiness}


def ml_truth_status(variant: dict[str, Any], ml: dict[str, Any] | None) -> str:
    payload = ml or {}
    if payload.get("ml_evidence_status") == "MISSING_EVIDENCE":
        return "MISSING_EVIDENCE"
    if payload.get("status") == "COMPLETED" and payload.get("model") and payload.get("prediction_quality"):
        return "REAL_COMPUTED_ML"
    if variant.get("theme") in {THEME_US_STOCK_MOMENTUM_QUALITY, THEME_US_STOCK_LOW_VOL_DEFENSIVE}:
        return "MISSING_EVIDENCE"
    if payload.get("status") in {"NO_ML_USED", "BLOCKED"}:
        return "NO_ML_USED"
    return "MISSING_EVIDENCE"


def evidence_manifest(
    variant_or_spec: dict[str, Any],
    backtest: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    ml: dict[str, Any] | None,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    metrics_payload = metrics or {}
    backtest_payload = backtest or {}
    status = backtest_payload.get("status") or "EVIDENCE_NOT_RUN"
    metrics_available = status == "COMPLETED" and metrics_payload.get("status") == "COMPLETED"
    return {
        "schema_version": "strategy_factory_evidence_manifest_v1",
        "generated_at": now_utc(),
        "generated_from_material": bool(variant_or_spec.get("generated_from_material")),
        "source_material_path": variant_or_spec.get("source_material_path"),
        "source_material_hash": variant_or_spec.get("source_material_hash"),
        "theme": variant_or_spec.get("theme"),
        "strategy_name": variant_or_spec.get("strategy_name"),
        "variant_id": variant_or_spec.get("variant_id"),
        "evidence_status": "EVIDENCE_AVAILABLE" if metrics_available else ("DATA_MISSING" if status == "BLOCKED" else "EVIDENCE_NOT_RUN"),
        "backtest_status": status,
        "input_universe_path": backtest_payload.get("input_universe_path") or MISSING_EVIDENCE,
        "tickers_used": backtest_payload.get("universe") or variant_or_spec.get("universe_or_proxy") or variant_or_spec.get("universe") or [],
        "date_range": metrics_payload.get("date_range") or backtest_payload.get("date_range") or MISSING_EVIDENCE,
        "price_data_source_path": backtest_payload.get("price_data_source_path") or MISSING_EVIDENCE,
        "signal_definition": backtest_payload.get("signal") or variant_or_spec.get("signal_formula") or MISSING_EVIDENCE,
        "benchmark": backtest_payload.get("benchmark") or variant_or_spec.get("benchmark") or MISSING_EVIDENCE,
        "transaction_cost_assumption": backtest_payload.get("cost_assumption_bps_per_side") or metrics_payload.get("cost_assumption_bps_per_side") or MISSING_EVIDENCE,
        "output_artifact_path": artifacts.get("evidence_report") or artifacts.get("evidence_manifest") or MISSING_EVIDENCE,
        "metrics": {
            "sharpe": metrics_payload.get("sharpe", MISSING_EVIDENCE),
            "annual_return": metrics_payload.get("annual_return", MISSING_EVIDENCE),
            "max_drawdown": metrics_payload.get("max_drawdown", MISSING_EVIDENCE),
            "volatility": metrics_payload.get("volatility", MISSING_EVIDENCE),
            "turnover": metrics_payload.get("turnover", MISSING_EVIDENCE),
            "turnover_value": metrics_payload.get("turnover_value", MISSING_EVIDENCE),
            "turnover_unit": metrics_payload.get("turnover_unit", MISSING_EVIDENCE),
            "turnover_frequency": metrics_payload.get("turnover_frequency", MISSING_EVIDENCE),
            "turnover_definition": metrics_payload.get("turnover_definition", MISSING_EVIDENCE),
            "average_rebalance_turnover": metrics_payload.get("average_rebalance_turnover", MISSING_EVIDENCE),
            "annualized_turnover": metrics_payload.get("annualized_turnover", MISSING_EVIDENCE),
            "cumulative_turnover": metrics_payload.get("cumulative_turnover", MISSING_EVIDENCE),
            "rebalance_frequency_per_year": metrics_payload.get("rebalance_frequency_per_year", MISSING_EVIDENCE),
        },
        "ml_truth_status": ml_truth_status(variant_or_spec, ml),
        "ml_summary": "No ML evidence available" if ml_truth_status(variant_or_spec, ml) == "MISSING_EVIDENCE" else (ml or {}).get("model", "No ML used"),
    }


def automation_readiness(
    variant_or_spec: dict[str, Any],
    backtest: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    evidence: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    if not variant_or_spec.get("generated_from_material"):
        ready = False
        reason = "GENERATED_FROM_STATIC_FIXTURE_ONLY"
    elif variant_or_spec.get("theme") in {None, "", THEME_UNKNOWN_REVIEW_REQUIRED}:
        ready = False
        reason = "UNKNOWN_MATERIAL"
    elif evidence.get("evidence_status") == "DATA_MISSING" or (backtest or {}).get("status") == "BLOCKED":
        ready = False
        reason = "DATA_MISSING"
    elif evidence.get("evidence_status") != "EVIDENCE_AVAILABLE":
        ready = False
        reason = "EVIDENCE_NOT_RUN"
    elif not artifacts.get("evidence_report"):
        ready = False
        reason = "EVIDENCE_LINEAGE_MISSING"
    elif (metrics or {}).get("status") != "COMPLETED":
        ready = False
        reason = "EVIDENCE_NOT_RUN"
    else:
        ready = True
        reason = "BACKTEST_METRICS_AVAILABLE"
        if evidence.get("ml_truth_status") == "MISSING_EVIDENCE":
            reason = "BACKTEST_METRICS_AVAILABLE; ML_MISSING_BUT_NOT_BLOCKING"
    return {
        "schema_version": "strategy_factory_automation_readiness_v1",
        "generated_at": now_utc(),
        "variant_id": variant_or_spec.get("variant_id"),
        "strategy_name": variant_or_spec.get("strategy_name"),
        "theme": variant_or_spec.get("theme"),
        "generated_from_material": bool(variant_or_spec.get("generated_from_material")),
        "evidence_status": evidence.get("evidence_status"),
        "backtest_status": evidence.get("backtest_status"),
        "ml_status": evidence.get("ml_truth_status"),
        "automation_ready": ready,
        "automation_block_reason": reason,
        "evidence_artifact_path": artifacts.get("evidence_report") or artifacts.get("evidence_manifest"),
        "display_message": "Automation-ready evidence gate passed." if ready else "Not automation-ready: evidence/backtest missing." if reason in {"DATA_MISSING", "EVIDENCE_NOT_RUN"} else f"Not automation-ready: {reason}.",
    }


def write_variant_readiness(
    evaluation_dir: Path,
    variant: dict[str, Any],
    backtest: dict[str, Any] | None,
    metrics: dict[str, Any] | None,
    ml: dict[str, Any] | None,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    evidence = evidence_manifest(variant, backtest, metrics, ml, artifacts)
    readiness = automation_readiness(variant, backtest, metrics, evidence, artifacts)
    evidence_path = evaluation_dir / "variant_evidence_manifest.json"
    readiness_path = evaluation_dir / "variant_readiness_status.json"
    write_json(evidence_path, evidence)
    write_json(readiness_path, readiness)
    return {"evidence_manifest": evidence, "readiness": readiness, "evidence_manifest_path": str(evidence_path), "readiness_status_path": str(readiness_path)}
