"""Bridge Workstation Strategy Factory views to alpha_research artifacts.

This adapter intentionally reads the existing Strategy Factory/workbench layout
instead of inventing a second dashboard-only artifact tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import csv
import hashlib
import importlib
import json
import math
import mimetypes
import os
import re
import sys


TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
PUBLIC_WARNING = "PUBLIC_FALLBACK_PROTOTYPE"
CANDIDATE_PORTFOLIO_DEFAULT = "NO_ELIGIBLE_CANDIDATES"


@dataclass(frozen=True)
class AlphaArtifactRoots:
    alpha_root: Path
    strategy_factory_root: Path
    workbench_root: Path
    workbench_data_root: Path
    uploads_dir: Path
    upload_batches_dir: Path
    material_text_dir: Path
    material_analysis_dir: Path
    run_plans_dir: Path
    research_cards_dir: Path
    test_specs_dir: Path
    experiments_roots: tuple[Path, ...]
    evidence_reports_dir: Path
    candidate_idea_registry: Path
    intake_items: Path


METRIC_UNAVAILABLE = "Metric unavailable in artifact."


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve_alpha_root(workstation_root: Path) -> Path | None:
    env_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    candidates = [
        Path(env_root) if env_root else None,
        workstation_root.parent / "alpha_research",
        Path("D:/Global_Ai/alpha_research"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()
    return None


def alpha_roots(workstation_root: Path) -> AlphaArtifactRoots | None:
    alpha_root = resolve_alpha_root(workstation_root)
    if alpha_root is None:
        return None
    strategy_factory_root = alpha_root / "strategy_factory"
    workbench_root = alpha_root / "strategy_factory_workbench"
    workbench_data_root = workbench_root / "workbench_data"
    return AlphaArtifactRoots(
        alpha_root=alpha_root,
        strategy_factory_root=strategy_factory_root,
        workbench_root=workbench_root,
        workbench_data_root=workbench_data_root,
        uploads_dir=workbench_data_root / "uploads",
        upload_batches_dir=workbench_data_root / "upload_batches",
        material_text_dir=workbench_data_root / "material_text",
        material_analysis_dir=workbench_data_root / "material_analysis",
        run_plans_dir=workbench_data_root / "run_plans",
        research_cards_dir=strategy_factory_root / "research_cards",
        test_specs_dir=strategy_factory_root / "codex_test_specs",
        experiments_roots=(strategy_factory_root / "experiments", alpha_root / "experiments"),
        evidence_reports_dir=strategy_factory_root / "evidence_reports",
        candidate_idea_registry=workbench_data_root / "candidate_idea_registry.json",
        intake_items=workbench_data_root / "intake_items.json",
    )


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def _read_text(path: Path | None, fallback: str = "") -> str:
    if not path or not path.exists():
        return fallback
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback


def _read_csv_rows(path: Path | None, limit: int | None = None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = []
            for row in reader:
                rows.append(dict(row))
                if limit is not None and len(rows) >= limit:
                    break
            return rows
    except OSError:
        return []


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _series_point(date: Any, value: Any) -> dict[str, Any] | None:
    number = _float_or_none(value)
    if number is None or not date:
        return None
    return {"date": str(date), "value": number}


def _downsample(points: list[dict[str, Any]], max_points: int = 750) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points
    step = max(1, math.ceil(len(points) / max_points))
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def _compound_series(rows: list[dict[str, str]], column: str) -> list[dict[str, Any]]:
    equity = 1.0
    points: list[dict[str, Any]] = []
    for row in rows:
        ret = _float_or_none(row.get(column))
        if ret is None:
            continue
        equity *= 1.0 + ret
        point = _series_point(row.get("date"), equity)
        if point:
            points.append(point)
    return _downsample(points)


def _drawdown_series(equity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak: float | None = None
    points: list[dict[str, Any]] = []
    for point in equity:
        value = _float_or_none(point.get("value"))
        if value is None:
            continue
        peak = value if peak is None else max(peak, value)
        points.append({"date": point["date"], "value": value / peak - 1.0 if peak else 0.0})
    return _downsample(points)


def _rolling_sharpe(rows: list[dict[str, str]], window: int = 63) -> list[dict[str, Any]]:
    returns: list[tuple[str, float]] = []
    for row in rows:
        ret = _float_or_none(row.get("net_return"))
        if ret is not None and row.get("date"):
            returns.append((str(row["date"]), ret))
    points: list[dict[str, Any]] = []
    for idx in range(window - 1, len(returns)):
        sample = [ret for _, ret in returns[idx - window + 1 : idx + 1]]
        mean = sum(sample) / len(sample)
        variance = sum((ret - mean) ** 2 for ret in sample) / max(1, len(sample) - 1)
        stdev = math.sqrt(variance)
        points.append({"date": returns[idx][0], "value": (mean / stdev) * math.sqrt(252) if stdev else 0.0})
    return _downsample(points)


def _monthly_returns(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        date = str(row.get("date") or "")
        if len(date) < 7:
            continue
        bucket = grouped.setdefault(date[:7], {"month": date[:7], "strategy": 1.0, "benchmark": 1.0, "has_benchmark": False})
        ret = _float_or_none(row.get("net_return"))
        bench = _float_or_none(row.get("benchmark_return"))
        if ret is not None:
            bucket["strategy"] *= 1.0 + ret
        if bench is not None:
            bucket["benchmark"] *= 1.0 + bench
            bucket["has_benchmark"] = True
    return [
        {
            "month": month,
            "strategy_return": bucket["strategy"] - 1.0,
            "benchmark_return": bucket["benchmark"] - 1.0 if bucket["has_benchmark"] else METRIC_UNAVAILABLE,
        }
        for month, bucket in sorted(grouped.items())
    ]


def _return_histogram(rows: list[dict[str, str]], bins: int = 12) -> list[dict[str, Any]]:
    returns = [value for value in (_float_or_none(row.get("net_return")) for row in rows) if value is not None]
    if not returns:
        return []
    lo, hi = min(returns), max(returns)
    if lo == hi:
        return [{"min": lo, "max": hi, "label": f"{lo:.4f}", "count": len(returns)}]
    width = (hi - lo) / bins
    counts = [0 for _ in range(bins)]
    for value in returns:
        idx = min(bins - 1, max(0, int((value - lo) / width)))
        counts[idx] += 1
    return [
        {"min": lo + idx * width, "max": lo + (idx + 1) * width, "label": f"{lo + idx * width:.3%} to {lo + (idx + 1) * width:.3%}", "count": count}
        for idx, count in enumerate(counts)
    ]


def _monthly_turnover_cost(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        date = str(row.get("date") or "")
        if len(date) < 7:
            continue
        bucket = grouped.setdefault(date[:7], {"month": date[:7], "turnover_sum": 0.0, "turnover_count": 0, "cost_drag": 0.0})
        turnover = _float_or_none(row.get("turnover"))
        cost = _float_or_none(row.get("cost_drag") or row.get("transaction_cost"))
        if turnover is not None:
            bucket["turnover_sum"] += turnover
            bucket["turnover_count"] += 1
        if cost is not None:
            bucket["cost_drag"] += cost
    return [
        {
            "month": month,
            "average_turnover": bucket["turnover_sum"] / bucket["turnover_count"] if bucket["turnover_count"] else METRIC_UNAVAILABLE,
            "cost_drag": bucket["cost_drag"],
        }
        for month, bucket in sorted(grouped.items())
    ]


def _candidate_chart_data(backtest_path: Path, backtest_payload: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    daily_path = backtest_path.parent / "daily_strategy_returns.csv"
    rows = _read_csv_rows(daily_path)
    meta = {
        "source_artifact_path": str(daily_path if daily_path.exists() else backtest_path),
        "data_range": metrics.get("date_range", METRIC_UNAVAILABLE),
        "benchmark": metrics.get("benchmark", backtest_payload.get("benchmark", METRIC_UNAVAILABLE)),
        "cost_assumption": metrics.get("cost_assumption", METRIC_UNAVAILABLE),
    }
    if not rows:
        return {"status": "SUMMARY_ONLY", "message": "Chart unavailable: missing real backtest series.", **meta, "summary_metrics": metrics}
    equity = _compound_series(rows, "net_return")
    benchmark = _compound_series(rows, "benchmark_return")
    if not equity:
        return {"status": "SUMMARY_ONLY", "message": "Chart unavailable: missing real backtest series.", **meta, "summary_metrics": metrics}
    return {
        "status": "AVAILABLE",
        "message": "Charts generated from candidate-specific daily_strategy_returns.csv.",
        **meta,
        "equity_curve": {"title": "Equity Curve vs Benchmark", "series": [{"label": "Strategy net equity", "values": equity}, {"label": "Benchmark equity", "values": benchmark}]},
        "drawdown": {"title": "Strategy Drawdown", "series": [{"label": "Strategy drawdown", "values": _drawdown_series(equity)}]},
        "rolling_sharpe": {"title": "Rolling Sharpe", "window": 63, "series": [{"label": "63D rolling Sharpe", "values": _rolling_sharpe(rows)}]},
        "monthly_returns": {"title": "Monthly Returns", "rows": _monthly_returns(rows)},
        "return_distribution": {"title": "Return Distribution", "bins": _return_histogram(rows)},
        "turnover_cost": {"title": "Turnover / Transaction Cost", "rows": _monthly_turnover_cost(rows)},
        "summary_metrics": metrics,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _rel(root: Path, path: Path | str | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.as_posix()


def _abs(root: AlphaArtifactRoots, path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root.alpha_root / candidate


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "uploaded_material"
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    return clean[:140] if clean else "uploaded_material"


def _slug(value: str, limit: int = 48) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.upper()).strip("._-")
    return clean[:limit] if clean else "MATERIAL"


def _material_id(batch_id: str, filename: str, index: int, content: bytes) -> str:
    digest = hashlib.sha1(batch_id.encode("utf-8") + filename.encode("utf-8") + content[:4096]).hexdigest()
    return f"MAT_{_slug(Path(filename).stem)}_{index:03d}_{digest[:10].upper()}"


def _phase_status(status: str) -> str:
    upper = status.upper()
    if upper == "EMPTY_FILE":
        return "METADATA_ONLY"
    if upper.startswith("EXTRACTED") or upper in {"CSV_HEADER_PREVIEW", "PDF_TEXT_PREVIEW", "EXCEL_METADATA_PREVIEW"}:
        return "EXTRACTED"
    if "UNSUPPORTED" in upper or upper.startswith("METADATA_ONLY"):
        return "METADATA_ONLY"
    if "FAILED" in upper or "ERROR" in upper:
        return "EXTRACTION_FAILED"
    return "METADATA_ONLY"


def _append_json_list(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = _read_json(path, [])
    if not isinstance(payload, list):
        payload = []
    existing = {str(row.get("material_id") or row.get("intake_id") or row.get("idea_id")) for row in payload if isinstance(row, dict)}
    for row in rows:
        key = str(row.get("material_id") or row.get("intake_id") or row.get("idea_id"))
        if key not in existing:
            payload.append(row)
            existing.add(key)
    _write_json(path, payload)


def _candidate_idea_id(analysis: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(analysis.get("material_id", "")),
            str(analysis.get("classification_guess", "")),
            str(analysis.get("filename", "")),
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10].upper()
    return f"IDEA_{_slug(Path(str(analysis.get('filename') or analysis.get('material_id') or 'MATERIAL')).stem, 72)}_{digest}"


def _strategy_id_from_experiment(name: str) -> str:
    for suffix in ("_EXPERIMENT_V0", "_EXPERIMENT", "_RUN"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _strategy_id_from_card(path: Path) -> str:
    stem = path.stem
    for suffix in ("_research_card_draft", "_research_card"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _strategy_id_from_spec(path: Path) -> str:
    stem = path.stem
    for suffix in ("_test_spec_draft", "_test_spec"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _metric(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return METRIC_UNAVAILABLE
        current = current[key]
    return current if current not in (None, "") else METRIC_UNAVAILABLE


def _candidate_metrics(backtest_payload: dict[str, Any]) -> dict[str, Any]:
    key_metrics = backtest_payload.get("key_metrics") if isinstance(backtest_payload.get("key_metrics"), dict) else {}
    cost = backtest_payload.get("cost_assumptions") if isinstance(backtest_payload.get("cost_assumptions"), dict) else {}
    test_period = backtest_payload.get("test_period") if isinstance(backtest_payload.get("test_period"), dict) else {}
    return {
        "sharpe": key_metrics.get("sharpe", METRIC_UNAVAILABLE),
        "annual_return": key_metrics.get("annualized_return", METRIC_UNAVAILABLE),
        "max_drawdown": key_metrics.get("max_drawdown", METRIC_UNAVAILABLE),
        "volatility": key_metrics.get("annualized_volatility", METRIC_UNAVAILABLE),
        "turnover": key_metrics.get("average_turnover", METRIC_UNAVAILABLE),
        "benchmark": backtest_payload.get("benchmark", METRIC_UNAVAILABLE),
        "date_range": (
            f"{test_period.get('start_date') or key_metrics.get('start_date')} to {test_period.get('end_date') or key_metrics.get('end_date')}"
            if (test_period.get("start_date") or key_metrics.get("start_date"))
            else METRIC_UNAVAILABLE
        ),
        "cost_assumption": (
            f"{cost.get('transaction_cost_bps')} bps"
            if cost.get("transaction_cost_bps") is not None
            else METRIC_UNAVAILABLE
        ),
    }


def _first_lines(text: str, limit: int = 900) -> str:
    clean = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return clean[:limit] if clean else ""


def _analysis_summary(analysis: dict[str, Any], extracted_chars: int) -> dict[str, Any]:
    ideas = analysis.get("candidate_ideas") if isinstance(analysis.get("candidate_ideas"), list) else []
    return {
        "document_summary": (
            f"Real alpha_research material analysis artifact loaded for {analysis.get('filename', 'material')}. "
            f"Extracted characters: {extracted_chars}."
        ),
        "key_themes": analysis.get("detected_keywords") or analysis.get("alpha_factors") or [],
        "strategy_concepts": [str(item.get("name")) for item in ideas if isinstance(item, dict) and item.get("name")],
        "signal_ideas": [str(item.get("description")) for item in ideas if isinstance(item, dict) and item.get("description")],
        "risk_filters": analysis.get("timing_risks") or analysis.get("lookahead_risks") or [],
        "data_requirements": analysis.get("required_data") or [],
        "implementation_blockers": analysis.get("rejection_or_block_reasons") or [],
        "source_classification": analysis.get("classification_guess") or "Unavailable",
        "testability": analysis.get("testability") or "Unavailable",
        "artifact_path": str(analysis.get("analysis_path") or ""),
    }


def _normalized_material(root: AlphaArtifactRoots, row: dict[str, Any]) -> dict[str, Any]:
    text_path = _abs(root, str(row.get("extracted_text_path") or ""))
    extracted_chars = 0
    if text_path and text_path.exists():
        try:
            extracted_chars = len(text_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            extracted_chars = 0
    raw_status = str(row.get("extraction_status") or "EXTRACTION_PENDING")
    phase = str(row.get("extraction_phase_status") or _phase_status(raw_status))
    if extracted_chars > 0 and phase == "EXTRACTED":
        display_status = "Extracted"
    elif raw_status.upper() == "EXTRACTION_PENDING":
        display_status = "Pending Extraction"
    else:
        display_status = "Unsupported Extraction"
    analysis_path = _abs(root, str(row.get("analysis_path") or ""))
    raw_analysis = _read_json(analysis_path, {}) if analysis_path else {}
    has_real_analysis = bool(raw_analysis) and extracted_chars > 0 and str(row.get("analysis_status", "")).upper() == "ANALYZED"
    analysis = _analysis_summary(raw_analysis, extracted_chars) if has_real_analysis else None
    if not analysis:
        analysis = {
            "document_summary": "Analysis is blocked because no valid extracted text artifact is available.",
            "key_themes": [],
            "strategy_concepts": [],
            "signal_ideas": [],
            "risk_filters": [],
            "data_requirements": [],
            "implementation_blockers": [f"{raw_status}: no valid extracted text artifact."],
            "source_classification": raw_analysis.get("classification_guess", "Unavailable") if isinstance(raw_analysis, dict) else "Unavailable",
            "testability": "Blocked until extraction succeeds.",
            "artifact_path": str(analysis_path) if analysis_path else "",
        }
    stored = _abs(root, str(row.get("stored_relative_path") or ""))
    return {
        "material_id": row.get("material_id"),
        "batch_id": row.get("batch_id"),
        "filename": row.get("original_filename") or row.get("filename") or row.get("stored_filename"),
        "stored_path": str(stored) if stored else str(row.get("stored_relative_path") or ""),
        "stored_relative_path": str(row.get("stored_relative_path") or ""),
        "uploaded_at": row.get("created_at") or "",
        "file_type": str(row.get("file_ext") or Path(str(row.get("original_filename", ""))).suffix).lstrip("."),
        "extraction_status": display_status,
        "raw_extraction_status": raw_status,
        "extraction_phase_status": phase,
        "extracted_text_path": str(text_path) if text_path else "",
        "extracted_character_count": extracted_chars,
        "analysis": analysis,
        "analysis_path": str(analysis_path) if analysis_path else "",
        "analysis_status": row.get("analysis_status") or "NOT_STARTED",
        "review_status": row.get("review_status") or "UNREVIEWED",
        "suggested_next_action": row.get("suggested_next_action") or "HUMAN_REVIEW_REQUIRED",
    }


def load_alpha_snapshot(workstation_root: Path) -> dict[str, Any] | None:
    roots = alpha_roots(workstation_root)
    if roots is None:
        return None
    batches = []
    materials = []
    for path in sorted(roots.upload_batches_dir.glob("*.json"), key=lambda item: item.name.lower(), reverse=True):
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        payload["manifest_path"] = str(path)
        batches.append(payload)
        for row in payload.get("files", []):
            if isinstance(row, dict):
                materials.append(_normalized_material(roots, row))
    ideas = _read_json(roots.candidate_idea_registry, [])
    if not isinstance(ideas, list):
        ideas = []
    research_cards = sorted(roots.research_cards_dir.glob("*.md")) if roots.research_cards_dir.exists() else []
    test_specs = sorted(roots.test_specs_dir.glob("*.md")) if roots.test_specs_dir.exists() else []
    run_plans = sorted(roots.run_plans_dir.glob("*.json")) if roots.run_plans_dir.exists() else []
    baseline: list[Path] = []
    robustness: list[Path] = []
    ml: list[Path] = []
    decisions: list[Path] = []
    for experiments_root in roots.experiments_roots:
        if not experiments_root.exists():
            continue
        baseline.extend(experiments_root.glob("*/outputs/baseline_summary.json"))
        robustness.extend(experiments_root.glob("*/outputs/robustness_summary.json"))
        ml.extend(experiments_root.glob("*/outputs/ml_diagnostics_summary.json"))
        decisions.extend(experiments_root.glob("*/outputs/decision_memo.md"))
        decisions.extend(experiments_root.glob("*/docs/decision_memo.md"))
    evidence_reports = sorted(roots.evidence_reports_dir.glob("*/evidence_report.md")) if roots.evidence_reports_dir.exists() else []
    candidates = build_candidate_registry_from_roots(roots, materials, ideas, research_cards, test_specs, run_plans, baseline, robustness, ml, evidence_reports, decisions)
    counts = {
        "uploaded_materials": len(materials),
        "extracted_materials": sum(1 for row in materials if row.get("extraction_status") == "Extracted" and row.get("extracted_character_count", 0) > 0),
        "extraction_failed": sum(1 for row in materials if row.get("extraction_status") == "Unsupported Extraction"),
        "extraction_pending": sum(1 for row in materials if row.get("extraction_status") == "Pending Extraction"),
        "analyzed_records": sum(1 for row in materials if row.get("extraction_status") == "Extracted" and row.get("extracted_character_count", 0) > 0 and row.get("analysis_path")),
        "prototype_seeds": 0,
        "candidate_ideas": len(ideas),
        "research_cards": len(research_cards),
        "test_specs": len(test_specs),
        "run_plans": len(run_plans),
        "backtest_results": len(baseline),
        "tested_candidates": len(baseline),
        "robustness_reports": len(robustness),
        "ml_diagnostics": len(ml),
        "evidence_reports": len(evidence_reports),
        "decisions": len(decisions),
        "portfolio_drafts": 0,
    }
    return {
        "available": True,
        "alpha_root": str(roots.alpha_root),
        "strategy_factory_root": str(roots.strategy_factory_root),
        "workbench_data_root": str(roots.workbench_data_root),
        "candidate_idea_registry": str(roots.candidate_idea_registry),
        "intake": {
            "schema_version": "alpha_strategy_factory_intake_manifest_bridge_v0",
            "materials": materials,
            "batches": batches,
            "source": str(roots.upload_batches_dir),
        },
        "ideas": ideas,
        "research_cards": [{"path": str(path), "strategy_id": path.stem.removesuffix("_research_card")} for path in research_cards],
        "test_specs": [{"path": str(path), "strategy_id": path.stem.removesuffix("_test_spec").removesuffix("_test_spec_draft")} for path in test_specs],
        "run_plans": [{"path": str(path), **(_read_json(path, {}) if isinstance(_read_json(path, {}), dict) else {})} for path in run_plans],
        "backtest_results": [{"path": str(path), "experiment": path.parent.parent.name, "payload": _read_json(path, {})} for path in baseline],
        "robustness_results": [{"path": str(path), "experiment": path.parent.parent.name, "payload": _read_json(path, {})} for path in robustness],
        "ml_diagnostics": [{"path": str(path), "experiment": path.parent.parent.name, "payload": _read_json(path, {})} for path in ml],
        "evidence_reports": [{"path": str(path), "strategy_id": path.parent.name} for path in evidence_reports],
        "decisions": [{"path": str(path), "experiment": path.parent.parent.name if path.parent.name in {"outputs", "docs"} else path.parent.name} for path in decisions],
        "candidates": candidates,
        "counts": counts,
    }


def build_candidate_registry_from_roots(
    roots: AlphaArtifactRoots,
    materials: list[dict[str, Any]],
    ideas: list[dict[str, Any]],
    research_cards: list[Path],
    test_specs: list[Path],
    run_plans: list[Path],
    baseline: list[Path],
    robustness: list[Path],
    ml: list[Path],
    evidence_reports: list[Path],
    decisions: list[Path],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    def ensure(strategy_id: str) -> dict[str, Any]:
        strategy_id = strategy_id.strip() or "UNKNOWN_CANDIDATE"
        row = by_id.setdefault(
            strategy_id,
            {
                "strategy_id": strategy_id,
                "candidate_id": strategy_id,
                "name": strategy_id.replace("_", " ").title(),
                "source_materials": [],
                "material_summaries": [],
                "source_evidence": {
                    "source_batch_ids": [],
                    "source_material_ids": [],
                    "directly_derived_from_uploads": False,
                    "honesty_note": "Candidate lineage is reconstructed from alpha_research artifacts.",
                    "artifact_chain": {},
                },
                "completed_stages": [],
                "safety_labels": ["PROTOTYPE_ONLY", "NOT_LIVE_TRADING", "NOT_INSTITUTIONAL_VALIDATION", "USER_CONFIRMATION_REQUIRED"],
                "source_derivation_status": "ALPHA_RESEARCH_ARTIFACT_LINEAGE",
                "portfolio_workflow": {
                    "candidate_status": "ALPHA_RESEARCH_CANDIDATE",
                    "in_candidate_portfolio": False,
                    "allocation_draft_exists": False,
                    "applied_to_paper": False,
                    "add_enabled": False,
                    "allocation_enabled": False,
                    "apply_enabled": False,
                },
                "report_sections": {},
                "chart_previews": [],
            },
        )
        return row

    materials_by_id = {str(row.get("material_id")): row for row in materials if row.get("material_id")}
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        strategy_id = str(idea.get("strategy_id") or idea.get("idea_id") or idea.get("title") or "IDEA_CANDIDATE")
        if strategy_id.startswith("IDEA_"):
            strategy_id = strategy_id.removeprefix("IDEA_")
        row = ensure(strategy_id)
        row["idea"] = idea
        row["idea_artifact_path"] = str(roots.candidate_idea_registry)
        row["name"] = str(idea.get("title") or idea.get("idea_id") or row["name"])
        row["strategy_thesis"] = str(idea.get("title") or idea.get("recommended_next_action") or "Candidate thesis unavailable in artifact.")
        source_material_ids = [str(x) for x in idea.get("source_material_ids", []) if x]
        source_batch_ids = [str(x) for x in idea.get("source_batch_ids", []) if x]
        row["source_evidence"]["source_material_ids"] = sorted(set(row["source_evidence"]["source_material_ids"] + source_material_ids))
        row["source_evidence"]["source_batch_ids"] = sorted(set(row["source_evidence"]["source_batch_ids"] + source_batch_ids))
        for material_id in source_material_ids:
            material = materials_by_id.get(material_id)
            if material and material not in row["source_materials"]:
                row["source_materials"].append(material)
                if material.get("analysis"):
                    row["material_summaries"].append(material["analysis"])

    for path in research_cards:
        strategy_id = _strategy_id_from_card(path)
        row = ensure(strategy_id)
        row["research_card"] = {"artifact_path": str(path), "summary": _first_lines(_read_text(path))}
        row["source_evidence"]["artifact_chain"]["research_card"] = str(path)
        row["completed_stages"].append("RESEARCH_CARD_CREATED")

    for path in test_specs:
        strategy_id = _strategy_id_from_spec(path)
        row = ensure(strategy_id)
        row["test_spec"] = {"artifact_path": str(path), "summary": _first_lines(_read_text(path))}
        row["source_evidence"]["artifact_chain"]["test_spec"] = str(path)
        row["completed_stages"].append("TEST_SPEC_CREATED")

    for path in run_plans:
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        strategy_id = str(payload.get("strategy_id") or payload.get("spec_id") or path.stem)
        row = ensure(strategy_id)
        row["run_plan"] = {**payload, "artifact_path": str(path)}
        row["source_evidence"]["artifact_chain"]["run_plan"] = str(path)
        row["completed_stages"].append("TEST_SPEC_CREATED")

    for path in baseline:
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        strategy_id = str(payload.get("strategy_id") or _strategy_id_from_experiment(path.parent.parent.name))
        row = ensure(strategy_id)
        metrics = _candidate_metrics(payload)
        row["name"] = str(payload.get("strategy_name") or row["name"])
        row["backtest_metrics"] = metrics
        row["chart_data"] = _candidate_chart_data(path, payload, metrics)
        row["benchmark"] = metrics["benchmark"]
        row["date_range"] = metrics["date_range"]
        row["cost_assumption"] = metrics["cost_assumption"]
        row["universe"] = payload.get("universe", "Metric unavailable in artifact.")
        row["decision_status"] = payload.get("decision_status") or payload.get("status") or "Metric unavailable in artifact."
        row["pipeline_stage"] = "BACKTEST_RUN"
        row["backtest_summary"] = {**payload, "artifact_path": str(path)}
        row["source_evidence"]["artifact_chain"]["backtest"] = str(path)
        row["completed_stages"].append("BACKTEST_RUN")

    for path in robustness:
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        strategy_id = str(payload.get("strategy_id") or _strategy_id_from_experiment(path.parent.parent.name))
        row = ensure(strategy_id)
        row["robustness"] = {**payload, "artifact_path": str(path)}
        row["source_evidence"]["artifact_chain"]["robustness"] = str(path)
        row["completed_stages"].append("ROBUSTNESS_RUN")

    for path in ml:
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        strategy_id = str(payload.get("strategy_id") or _strategy_id_from_experiment(path.parent.parent.name))
        row = ensure(strategy_id)
        row["ml_model_used"] = payload.get("top_diagnostic_model") or payload.get("top_model") or "Metric unavailable in artifact."
        row["ml_result_summary"] = payload.get("ml_diagnostics_decision") or payload.get("status") or "Metric unavailable in artifact."
        row["ml_diagnostics"] = {
            **payload,
            "artifact_path": str(path),
            "model": row["ml_model_used"],
            "top_diagnostic_metric": payload.get("top_diagnostic_metric", "Metric unavailable in artifact."),
            "top_diagnostic_value": payload.get("top_diagnostic_value", "Metric unavailable in artifact."),
        }
        row["source_evidence"]["artifact_chain"]["ml_diagnostics"] = str(path)
        row["completed_stages"].append("ML_DIAGNOSTICS_RUN")

    for path in evidence_reports:
        strategy_id = path.parent.name
        row = ensure(strategy_id)
        text = _read_text(path)
        row["report_path"] = str(path)
        row["report_sections"]["Executive Summary"] = _first_lines(text)
        row["report_sections"]["Limitations"] = "See evidence report artifact for missing evidence and limitations."
        row["source_evidence"]["artifact_chain"]["evidence"] = str(path)
        row["completed_stages"].append("EVIDENCE_REPORT_CREATED")

    for path in decisions:
        strategy_id = _strategy_id_from_experiment(path.parent.parent.name if path.parent.name in {"outputs", "docs"} else path.parent.name)
        row = ensure(strategy_id)
        row["decision_memo"] = {"artifact_path": str(path), "summary": _first_lines(_read_text(path))}
        row["source_evidence"]["artifact_chain"]["decision"] = str(path)
        row["completed_stages"].append("DECISION_CREATED")

    for row in by_id.values():
        row["completed_stages"] = sorted(set(row.get("completed_stages") or []))
        row["pipeline_stage"] = row.get("pipeline_stage") or (row["completed_stages"][-1] if row["completed_stages"] else "CANDIDATE_IDEA")
        row["strategy_thesis"] = row.get("strategy_thesis") or row.get("report_sections", {}).get("Executive Summary") or row.get("name")
        row["signal_formula"] = row.get("signal_formula", "Metric unavailable in artifact.")
        row["rebalance_frequency"] = row.get("rebalance_frequency", "Metric unavailable in artifact.")
        row["holding_period"] = row.get("holding_period", "Metric unavailable in artifact.")
        row["where_it_made_money"] = "See candidate-specific backtest/evidence artifacts."
        row["where_it_lost_money"] = "See candidate-specific drawdown/evidence artifacts."
        row["next_action"] = "Review candidate-specific artifacts; do not treat research outputs as admission."
        row["source_evidence"]["directly_derived_from_uploads"] = bool(row["source_evidence"]["source_material_ids"])
        row["source_evidence"]["uploaded_material_count"] = len(row["source_materials"])
        row["source_evidence"]["extracted_material_count"] = sum(1 for item in row["source_materials"] if item.get("extraction_status") == "Extracted")
        row["source_evidence"]["analyzed_material_count"] = sum(1 for item in row["source_materials"] if item.get("analysis_path"))
        row["monitor_ready_summary"] = {
            "pnl": "Research artifact only; not paper-applied.",
            "sharpe": row.get("backtest_metrics", {}).get("sharpe", METRIC_UNAVAILABLE),
            "drawdown": row.get("backtest_metrics", {}).get("max_drawdown", METRIC_UNAVAILABLE),
            "correlation": row.get("backtest_summary", {}).get("key_metrics", {}).get("benchmark_correlation", METRIC_UNAVAILABLE),
            "risk_contribution": "Metric unavailable in artifact.",
            "paper_portfolio_status": "NOT_APPLIED",
        }

    return sorted(
        by_id.values(),
        key=lambda row: (
            0 if row.get("backtest_metrics") else 1,
            0 if row.get("evidence_report") or row.get("report_path") else 1,
            str(row.get("strategy_id")),
        ),
    )


def _import_workbench_module(workstation_root: Path, module_name: str):
    roots = alpha_roots(workstation_root)
    if roots is None:
        raise FileNotFoundError("alpha_research root not found")
    module_roots = [roots.alpha_root, roots.workbench_root]
    fallback_alpha = Path("D:/Global_Ai/alpha_research")
    if fallback_alpha.exists() and fallback_alpha not in module_roots:
        module_roots.extend([fallback_alpha, fallback_alpha / "strategy_factory_workbench"])
    for entry in module_roots:
        entry_text = str(entry)
        if entry_text not in sys.path:
            sys.path.insert(0, entry_text)
    try:
        return importlib.import_module(f"strategy_factory_workbench.document_intelligence.{module_name}")
    except ModuleNotFoundError:
        return importlib.import_module(f"document_intelligence.{module_name}")


def save_uploads_to_alpha(workstation_root: Path, materials: Iterable[Any]) -> dict[str, Any]:
    roots = alpha_roots(workstation_root)
    if roots is None:
        raise FileNotFoundError("alpha_research root not found")
    for directory in (
        roots.uploads_dir,
        roots.upload_batches_dir,
        roots.material_text_dir,
        roots.material_analysis_dir,
        roots.run_plans_dir,
        roots.research_cards_dir,
        roots.test_specs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    material_schema = _import_workbench_module(workstation_root, "material_schema")
    text_extractors = _import_workbench_module(workstation_root, "text_extractors")
    material_analyzer = _import_workbench_module(workstation_root, "material_analyzer")
    research_card_drafter = _import_workbench_module(workstation_root, "research_card_drafter")
    test_spec_drafter = _import_workbench_module(workstation_root, "test_spec_drafter")
    run_plan_schema = _import_workbench_module(workstation_root, "run_plan_schema")

    material_list = list(materials)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(b"".join(item.content[:512] for item in material_list)).hexdigest()[:8].upper() if material_list else "EMPTY"
    batch_id = f"BATCH_{timestamp}_{digest}"
    batch_dir = roots.uploads_dir / batch_id
    collision_index = 1
    while batch_dir.exists():
        batch_id = f"BATCH_{timestamp}_{digest}_{collision_index}"
        batch_dir = roots.uploads_dir / batch_id
        collision_index += 1
    batch_dir.mkdir(parents=True)

    created_at = now_utc()
    files: list[dict[str, Any]] = []
    intake_rows: list[dict[str, Any]] = []
    new_ideas: list[dict[str, Any]] = []
    generated_cards: list[str] = []
    generated_specs: list[str] = []
    generated_run_plans: list[str] = []
    for index, material in enumerate(material_list, start=1):
        original = Path(material.filename).name or "uploaded_material"
        safe_name = material_schema.safe_filename(original) if hasattr(material_schema, "safe_filename") else _safe_filename(original)
        stored_filename = f"{index:03d}_{safe_name}"
        destination = batch_dir / stored_filename
        content = material.content if isinstance(material.content, bytes) else bytes(material.content)
        destination.write_bytes(content)
        material_id = (
            material_schema.make_material_id(batch_id, original, index, content)
            if hasattr(material_schema, "make_material_id")
            else _material_id(batch_id, original, index, content)
        )
        suffix = destination.suffix.lower()
        extraction = text_extractors.extract_text_or_metadata(destination, roots.material_text_dir, material_id)
        raw_status = str(extraction.get("extraction_status", "METADATA_ONLY_UNAVAILABLE"))
        phase = _phase_status(raw_status)
        extracted_path = extraction.get("extracted_text_path")
        extracted_rel = _rel(roots.alpha_root, extracted_path) if extracted_path else ""
        row = {
            "material_id": material_id,
            "batch_id": batch_id,
            "original_filename": original,
            "stored_filename": stored_filename,
            "stored_relative_path": _rel(roots.alpha_root, destination),
            "file_ext": suffix,
            "file_size_bytes": len(content),
            "sha256_hash": hashlib.sha256(content).hexdigest(),
            "mime_type_guess": extraction.get("mime_type_guess") or mimetypes.guess_type(original)[0] or "application/octet-stream",
            "source_type_guess": material_schema.guess_source_type(original) if hasattr(material_schema, "guess_source_type") else "UNKNOWN",
            "classification_guess": "NEEDS_AI_REVIEW",
            "object_type_guess": "US_EQUITY_ALPHA_STRATEGY",
            "status": phase,
            "upload_status": "UPLOADED",
            "extraction_status": raw_status,
            "extraction_phase_status": phase,
            "analysis_status": "NOT_STARTED",
            "review_status": "UNREVIEWED",
            "duplicate_status": "UNIQUE",
            "duplicate_of_material_id": "",
            "error_message": "",
            "retry_count": 0,
            "needs_ai_review": bool(extraction.get("needs_ai_review")),
            "extracted_text_path": extracted_rel,
            "preview_text": str(extraction.get("preview_text", "")),
            "notes": extraction.get("notes", []),
            "extraction_metadata": extraction.get("metadata", {}),
            "created_at": created_at,
            "data_readiness": PUBLIC_WARNING,
            "candidate_portfolio_status": CANDIDATE_PORTFOLIO_DEFAULT,
        }
        if phase == "EXTRACTED" and extracted_rel:
            analysis = material_analyzer.analyze_material(row, {
                "file_ext": suffix,
                "mime_type_guess": row["mime_type_guess"],
                "extraction_status": raw_status,
                "extracted_text_path": extracted_rel,
                "preview_text": row["preview_text"],
                "needs_ai_review": row["needs_ai_review"],
                "notes": row["notes"],
                "metadata": row["extraction_metadata"],
            })
            analysis["created_at"] = created_at
            analysis["analysis_status"] = "ANALYZED"
            analysis["upload_status"] = "UPLOADED"
            analysis["stored_relative_path"] = row["stored_relative_path"]
            analysis["duplicate_status"] = "UNIQUE"
            analysis["sha256_hash"] = row["sha256_hash"]
            analysis_path = roots.material_analysis_dir / f"{material_id}.json"
            _write_json(analysis_path, analysis)
            row["analysis_status"] = "ANALYZED"
            row["analysis_path"] = _rel(roots.alpha_root, analysis_path)
            row["classification_guess"] = analysis.get("classification_guess", row["classification_guess"])
            row["object_type_guess"] = analysis.get("object_type_guess", row["object_type_guess"])
            row["suggested_next_action"] = analysis.get("suggested_next_action", "HUMAN_REVIEW_REQUIRED")
            row["testability"] = analysis.get("testability", "Not Available")
            idea = {
                "idea_id": _candidate_idea_id(analysis),
                "title": (analysis.get("candidate_ideas") or [{"name": "Material-Derived Research Idea"}])[0].get("name", "Material-Derived Research Idea"),
                "created_at": created_at,
                "source_batch_ids": [batch_id],
                "source_material_ids": [material_id],
                "classification": analysis.get("classification_guess", "NEEDS_AI_REVIEW"),
                "object_type": analysis.get("object_type_guess", "US_EQUITY_ALPHA_STRATEGY"),
                "strategy_family": ", ".join(analysis.get("alpha_factors") or []),
                "testability": analysis.get("testability", "Not Available"),
                "evidence_status": "Missing Evidence",
                "research_card_status": "DRAFT_CREATED",
                "test_spec_status": "DRAFT_CREATED",
                "run_plan_status": "REVIEW_REQUIRED",
                "candidate_portfolio_status": CANDIDATE_PORTFOLIO_DEFAULT,
                "review_status": analysis.get("suggested_next_action", "HUMAN_REVIEW_REQUIRED"),
                "recommended_next_action": analysis.get("suggested_next_action", "HUMAN_REVIEW_REQUIRED"),
                "minimum_data_readiness_level": PUBLIC_WARNING,
            }
            new_ideas.append(idea)
            card_id = f"INTAKE_{material_id}_research_card_draft"
            spec_id = f"INTAKE_{material_id}_test_spec_draft"
            card_path = roots.research_cards_dir / f"{card_id}.md"
            spec_path = roots.test_specs_dir / f"{spec_id}.md"
            card_path.write_text(research_card_drafter.render_research_card_markdown(analysis, row["stored_relative_path"]), encoding="utf-8")
            spec_path.write_text(test_spec_drafter.render_test_spec_markdown(analysis, _rel(roots.alpha_root, card_path)), encoding="utf-8")
            run_plan = run_plan_schema.build_run_plan(spec_id, _rel(roots.alpha_root, spec_path), roots.alpha_root / "experiments", spec_path.read_text(encoding="utf-8"))
            run_plan_path = roots.run_plans_dir / f"{run_plan['run_plan_id']}.json"
            _write_json(run_plan_path, run_plan)
            generated_cards.append(str(card_path))
            generated_specs.append(str(spec_path))
            generated_run_plans.append(str(run_plan_path))
        files.append(row)
        intake_rows.append(
            {
                "intake_id": f"WB_INTAKE_{_slug(Path(original).stem, 72)}_{hashlib.sha1(content[:4096]).hexdigest()[:8].upper()}",
                "created_at": created_at,
                "filename": original,
                "title": Path(original).stem,
                "upload_path": row["stored_relative_path"],
                "size_bytes": len(content),
                "source_type": row["source_type_guess"],
                "object_type": row["object_type_guess"],
                "classification": row["classification_guess"],
                "workbench_status": row["status"],
                "data_readiness": PUBLIC_WARNING,
                "candidate_portfolio_status": CANDIDATE_PORTFOLIO_DEFAULT,
                "preview_text": row["preview_text"][:500],
                "recommended_next_action": row.get("suggested_next_action", "HUMAN_REVIEW_REQUIRED"),
                "origin": "workstation_strategy_factory_bridge",
            }
        )

    manifest = {
        "batch_id": batch_id,
        "created_at": created_at,
        "file_count": len(files),
        "files": files,
        "status": "BATCH_ANALYZED_REVIEW_REQUIRED" if any(row.get("analysis_status") == "ANALYZED" for row in files) else "BATCH_EXTRACTED_REVIEW_REQUIRED",
        "warning": PUBLIC_WARNING,
        "warnings": [PUBLIC_WARNING],
        "analysis_provider": "RULES_ONLY",
        "candidate_portfolio_status": CANDIDATE_PORTFOLIO_DEFAULT,
        "upload_root": _rel(roots.alpha_root, batch_dir),
        "generated_artifacts": {
            "research_cards": generated_cards,
            "test_specs": generated_specs,
            "run_plans": generated_run_plans,
            "candidate_idea_registry": str(roots.candidate_idea_registry),
        },
    }
    _write_json(roots.upload_batches_dir / f"{batch_id}.json", manifest)
    _append_json_list(roots.intake_items, intake_rows)
    _append_json_list(roots.candidate_idea_registry, new_ideas)
    snapshot = load_alpha_snapshot(workstation_root) or {}
    saved = [_normalized_material(roots, row) for row in files]
    return {"ok": True, "batch_id": batch_id, "saved": saved, "manifest": manifest, "snapshot": snapshot}


def create_selected_run_manifests(
    workstation_root: Path,
    selected_material_ids: list[str] | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    roots = alpha_roots(workstation_root)
    if roots is None:
        raise FileNotFoundError("alpha_research root not found")
    snapshot = load_alpha_snapshot(workstation_root)
    if snapshot is None:
        raise FileNotFoundError("alpha_research root not found")
    materials = snapshot.get("intake", {}).get("materials", [])
    selected_ids = {str(item) for item in (selected_material_ids or []) if str(item).strip()}
    if batch_id:
        selected = [row for row in materials if str(row.get("batch_id")) == batch_id]
    elif selected_ids:
        selected = [row for row in materials if str(row.get("material_id")) in selected_ids]
    else:
        selected = []
    if not selected:
        raise ValueError("Select materials for current batch first.")

    run_id = f"SF_RUN_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha1('|'.join(sorted(str(row.get('material_id')) for row in selected)).encode('utf-8')).hexdigest()[:8].upper()}"
    scoped_batch_id = batch_id or f"BATCH_SCOPE_{run_id}"
    run_dir = workstation_root / "output" / "strategy_factory" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    extracted_ideas = [
        idea
        for row in selected
        for idea in (row.get("analysis", {}) or {}).get("strategy_concepts", [])
    ]
    selected_materials_path = run_dir / "selected_materials.json"
    material_summary_path = run_dir / "material_summary.json"
    extracted_ideas_path = run_dir / "extracted_ideas.json"
    run_log_path = run_dir / "run_log.txt"
    _write_json(selected_materials_path, selected)
    _write_json(
        material_summary_path,
        {
            "schema_version": "strategy_factory_material_summary_v0",
            "run_id": run_id,
            "batch_id": scoped_batch_id,
            "materials": [
                {
                    "material_id": row.get("material_id"),
                    "filename": row.get("filename"),
                    "extraction_status": row.get("extraction_status"),
                    "extracted_character_count": row.get("extracted_character_count"),
                    "analysis": row.get("analysis"),
                    "analysis_path": row.get("analysis_path"),
                }
                for row in selected
            ],
        },
    )
    _write_json(
        extracted_ideas_path,
        {
            "schema_version": "strategy_factory_extracted_ideas_v0",
            "run_id": run_id,
            "batch_id": scoped_batch_id,
            "ideas": extracted_ideas,
            "source_material_ids": [row.get("material_id") for row in selected],
        },
    )
    run_log_path.write_text(
        "\n".join(
            [
                f"{now_utc()} RUN_CREATED {run_id}",
                f"{now_utc()} SELECTED_MATERIALS {', '.join(str(row.get('material_id')) for row in selected)}",
                f"{now_utc()} MATERIAL_SUMMARY_WRITTEN {material_summary_path}",
                f"{now_utc()} EXTRACTED_IDEAS_WRITTEN {extracted_ideas_path}",
                "BACKTEST NOT_IMPLEMENTED / BLOCKED",
                "ML NOT_IMPLEMENTED / BLOCKED",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    generated_paths = {
        "selected_materials": str(selected_materials_path),
        "material_summary": str(material_summary_path),
        "extracted_ideas": str(extracted_ideas_path),
        "run_log": str(run_log_path),
        "material_summaries": [row.get("analysis_path") for row in selected if row.get("analysis_path")],
        "extraction_artifacts": [row.get("extracted_text_path") for row in selected if row.get("extracted_text_path")],
        "research_cards": [
            str(path)
            for row in selected
            for path in roots.research_cards_dir.glob(f"*{row.get('material_id')}*.md")
        ],
        "test_specs": [
            str(path)
            for row in selected
            for path in roots.test_specs_dir.glob(f"*{row.get('material_id')}*.md")
        ],
        "candidate_ideas": extracted_ideas,
    }
    batch_manifest = {
        "schema_version": "strategy_factory_selected_batch_manifest_v0",
        "batch_id": scoped_batch_id,
        "run_id": run_id,
        "created_at": now_utc(),
        "selected_material_ids": [row.get("material_id") for row in selected],
        "selected_materials": selected,
        "source": "ALPHA_RESEARCH_BRIDGE",
        "status": "SELECTED_BATCH_READY",
    }
    run_manifest = {
        "schema_version": "strategy_factory_run_manifest_v0",
        "run_id": run_id,
        "batch_id": scoped_batch_id,
        "created_at": now_utc(),
        "selected_material_ids": [row.get("material_id") for row in selected],
        "selected_material_names": [row.get("filename") for row in selected],
        "selected_material_count": len(selected),
        "source_artifact_paths": generated_paths,
        "generated_artifacts": generated_paths,
        "status": "SCOPED_RUN_CREATED",
        "errors": [],
        "candidate_output": {
            "strategy_id": f"RUN_SCOPED_CANDIDATE_{run_id}",
            "source_material_ids": [row.get("material_id") for row in selected],
            "source_batch_id": scoped_batch_id,
            "source_run_id": run_id,
            "prototype_only": True,
        },
    }
    batch_path = run_dir / "batch_manifest.json"
    run_path = run_dir / "run_manifest.json"
    _write_json(batch_path, batch_manifest)
    _write_json(run_path, run_manifest)
    return {
        "run_id": run_id,
        "batch_id": scoped_batch_id,
        "selected_materials": selected,
        "selected_material_ids": [row.get("material_id") for row in selected],
        "batch_manifest_path": str(batch_path),
        "run_manifest_path": str(run_path),
        "batch_manifest": batch_manifest,
        "run_manifest": run_manifest,
    }
