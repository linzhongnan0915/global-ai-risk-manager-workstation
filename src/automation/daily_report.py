"""Daily Report artifact V0.

Aggregates existing paper/shadow workstation evidence into a durable daily
report artifact. Generation writes only the report artifact; all input reads are
from existing local builders or latest artifact readers.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.allocation_recommendation_artifact import read_latest_allocation_recommendation_artifact
from src.automation.daily_recommendation_artifact import read_latest_daily_recommendation_artifact
from src.automation.paper_allocation_proposal import read_latest_paper_allocation_proposal
from src.automation.risk_evidence import read_latest_risk_evidence_artifact
from src.automation.strategy_factory_selected_batch_job import read_latest_strategy_factory_job
from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.reporting.operational_snapshot import load_snapshot_summary_for_response
from src.strategy_intelligence import build_strategy_intelligence_payload


SOURCE = "daily_report_artifact_v0"
SCHEMA_VERSION = "0.1.0"
ARTIFACT_DIR = Path("data/automation/daily_reports")
BASE_LABELS = ["Prototype Only", "Paper Only", "Institutional Validation Pending"]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _latest_json_path(folder: Path) -> Path | None:
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def _source_record(name: str, latest: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(latest.get("ok")),
        "status": latest.get("status") or ("AVAILABLE" if latest.get("ok") else "MISSING_ARTIFACT"),
        "artifact_path": latest.get("artifact_path"),
        "source": latest.get("source"),
    }


def _risk_metric_status(risk_artifact: dict[str, Any], metric_name: str) -> str:
    portfolio = risk_artifact.get("portfolio_risk_evidence") if isinstance(risk_artifact.get("portfolio_risk_evidence"), dict) else {}
    metrics = portfolio.get("risk_metrics") if isinstance(portfolio.get("risk_metrics"), dict) else {}
    metric = metrics.get(metric_name) if isinstance(metrics, dict) else {}
    return str(metric.get("status") or risk_artifact.get("status") or "MISSING_DATA") if isinstance(metric, dict) else "MISSING_DATA"


def _risk_metric_value(risk_artifact: dict[str, Any], metric_name: str) -> Any:
    portfolio = risk_artifact.get("portfolio_risk_evidence") if isinstance(risk_artifact.get("portfolio_risk_evidence"), dict) else {}
    metrics = portfolio.get("risk_metrics") if isinstance(portfolio.get("risk_metrics"), dict) else {}
    metric = metrics.get(metric_name) if isinstance(metrics, dict) else {}
    return metric.get("value") if isinstance(metric, dict) else None


def _portfolio_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "AVAILABLE" if snapshot.get("ok") else "MISSING_ARTIFACT",
        "snapshot_id": snapshot.get("snapshot_id"),
        "generated_at": snapshot.get("generated_at"),
        "portfolio_summary": snapshot.get("portfolio_summary") if isinstance(snapshot.get("portfolio_summary"), dict) else {},
        "counts": snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {},
        "session_state": snapshot.get("session_state") if isinstance(snapshot.get("session_state"), dict) else {},
        "safety": snapshot.get("safety") if isinstance(snapshot.get("safety"), dict) else {},
    }


def _allocation_summary(
    daily_latest: dict[str, Any],
    allocation_latest: dict[str, Any],
    proposal_latest: dict[str, Any],
    paper_rebalance: dict[str, Any],
) -> dict[str, Any]:
    daily = daily_latest.get("artifact") if isinstance(daily_latest.get("artifact"), dict) else {}
    allocation = allocation_latest.get("artifact") if isinstance(allocation_latest.get("artifact"), dict) else {}
    proposal = proposal_latest.get("proposal") or proposal_latest.get("artifact") if isinstance(proposal_latest, dict) else {}
    return {
        "daily_recommendation_status": daily_latest.get("status") or "MISSING_ARTIFACT",
        "daily_recommendation_summary": daily.get("summary") if isinstance(daily.get("summary"), dict) else {},
        "allocation_recommendation_status": allocation_latest.get("status") or "MISSING_ARTIFACT",
        "allocation_summary": allocation.get("summary") if isinstance(allocation.get("summary"), dict) else {},
        "paper_allocation_proposal_status": proposal_latest.get("status") or "MISSING_ARTIFACT",
        "paper_allocation_proposal_summary": proposal.get("summary") if isinstance(proposal, dict) else {},
        "paper_rebalance_status": {
            "paper_only": paper_rebalance.get("paper_only"),
            "execution_mode": paper_rebalance.get("execution_mode"),
            "brokerage_execution": paper_rebalance.get("brokerage_execution"),
            "latest_plan_status": (paper_rebalance.get("latest_plan") or {}).get("status")
            if isinstance(paper_rebalance.get("latest_plan"), dict)
            else None,
            "approved_plan_status": (paper_rebalance.get("approved_rebalance") or {}).get("status")
            if isinstance(paper_rebalance.get("approved_rebalance"), dict)
            else None,
        },
    }


def _factory_summary(latest_job: dict[str, Any]) -> dict[str, Any]:
    job = latest_job.get("job") if isinstance(latest_job.get("job"), dict) else {}
    outputs = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
    output_counts = {
        key: len(value) if isinstance(value, list) else 0
        for key, value in outputs.items()
    }
    return {
        "status": latest_job.get("status") or "MISSING_ARTIFACT",
        "artifact_path": latest_job.get("artifact_path"),
        "job_id": job.get("job_id"),
        "selected_material_count": job.get("selected_material_count"),
        "selection_source": job.get("selection_source"),
        "output_counts": output_counts,
        "missing_output_count": sum(
            1
            for rows in outputs.values()
            if isinstance(rows, list)
            for row in rows
            if isinstance(row, dict) and row.get("exists") is False
        ),
    }


def _strategy_intelligence_summary(strategy_payload: dict[str, Any]) -> dict[str, Any]:
    summary = strategy_payload.get("summary") if isinstance(strategy_payload.get("summary"), dict) else {}
    cards = strategy_payload.get("cards") if isinstance(strategy_payload.get("cards"), list) else []
    missing_labels: dict[str, int] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        for label in card.get("missing_evidence") or []:
            missing_labels[str(label)] = missing_labels.get(str(label), 0) + 1
    return {
        "status": "AVAILABLE" if strategy_payload.get("ok") else "MISSING_ARTIFACT",
        "summary": summary,
        "card_count": len(cards),
        "missing_evidence_counts": missing_labels,
    }


def _risk_evidence_summary(latest_risk: dict[str, Any]) -> dict[str, Any]:
    if not latest_risk.get("ok"):
        return {
            "status": "MISSING_ARTIFACT",
            "artifact_path": None,
            "var_status": "MISSING_ARTIFACT",
            "cvar_status": "MISSING_ARTIFACT",
            "drawdown_stress_status": "MISSING_ARTIFACT",
            "realized_volatility_status": "MISSING_ARTIFACT",
            "labels": BASE_LABELS + ["Missing Risk Evidence"],
            "missing_reason": latest_risk.get("message") or "Risk evidence artifact is missing.",
        }
    artifact = latest_risk.get("artifact") if isinstance(latest_risk.get("artifact"), dict) else {}
    return {
        "status": latest_risk.get("status") or "AVAILABLE",
        "artifact_path": latest_risk.get("artifact_path"),
        "observation_count": artifact.get("observation_count"),
        "window_start": artifact.get("window_start"),
        "window_end": artifact.get("window_end"),
        "var_status": _risk_metric_status(artifact, "historical_var_95"),
        "cvar_status": _risk_metric_status(artifact, "historical_cvar_95"),
        "drawdown_stress_status": _risk_metric_status(artifact, "max_drawdown"),
        "realized_volatility_status": _risk_metric_status(artifact, "realized_volatility"),
        "max_drawdown": _risk_metric_value(artifact, "max_drawdown"),
        "labels": artifact.get("labels") if isinstance(artifact.get("labels"), list) else BASE_LABELS,
        "missing_data": artifact.get("missing_data") if isinstance(artifact.get("missing_data"), list) else [],
    }


def _daily_actions(daily_latest: dict[str, Any], strategy_payload: dict[str, Any]) -> list[dict[str, Any]]:
    daily = daily_latest.get("artifact") if isinstance(daily_latest.get("artifact"), dict) else {}
    recommendations = daily.get("recommendations") if isinstance(daily.get("recommendations"), list) else []
    if recommendations:
        return [
            {
                "strategy_uid": row.get("strategy_uid"),
                "recommended_action": row.get("recommended_action"),
                "confidence": row.get("confidence"),
                "reason": row.get("reason"),
                "risk_warning": row.get("risk_warning"),
            }
            for row in recommendations
            if isinstance(row, dict)
        ]
    cards = strategy_payload.get("cards") if isinstance(strategy_payload.get("cards"), list) else []
    return [
        {
            "strategy_uid": card.get("strategy_uid"),
            "recommended_action": card.get("decision_recommendation"),
            "confidence": "REVIEW_REQUIRED" if card.get("missing_evidence") else "UNSPECIFIED",
            "reason": "Derived from Strategy Intelligence card because daily recommendation artifact is unavailable.",
            "risk_warning": "; ".join(card.get("missing_evidence") or []) or None,
        }
        for card in cards
        if isinstance(card, dict)
    ]


def _missing_evidence(
    sources: list[dict[str, Any]],
    strategy_summary: dict[str, Any],
    risk_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for source in sources:
        if not source.get("ok"):
            missing.append(
                {
                    "source": source.get("name"),
                    "status": "Missing Artifact",
                    "missing_reason": f"{source.get('name')} artifact is unavailable.",
                }
            )
    for label, count in (strategy_summary.get("missing_evidence_counts") or {}).items():
        if count:
            missing.append({"source": "strategy_intelligence", "status": label, "count": count})
    if risk_summary.get("var_status") in {"INSUFFICIENT_HISTORY", "MISSING_ARTIFACT", "MISSING_DATA"}:
        missing.append(
            {
                "source": "risk_evidence",
                "status": risk_summary.get("var_status"),
                "missing_reason": "Historical VaR evidence is not fully available.",
            }
        )
    if risk_summary.get("cvar_status") in {"INSUFFICIENT_HISTORY", "MISSING_ARTIFACT", "MISSING_DATA"}:
        missing.append(
            {
                "source": "risk_evidence",
                "status": risk_summary.get("cvar_status"),
                "missing_reason": "Historical CVaR evidence is not fully available.",
            }
        )
    return missing


def _warnings(missing: list[dict[str, Any]], risk_summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    statuses = {str(item.get("status")) for item in missing}
    if "Missing ML Evidence" in statuses:
        warnings.append("Strategy Intelligence reports Missing ML Evidence.")
    if "Missing Attribution" in statuses:
        warnings.append("Strategy Intelligence reports Missing Attribution.")
    if risk_summary.get("var_status") == "INSUFFICIENT_HISTORY" or risk_summary.get("cvar_status") == "INSUFFICIENT_HISTORY":
        warnings.append("Risk evidence exists, but VaR/CVaR have insufficient history.")
    if any(item.get("status") == "Missing Artifact" for item in missing):
        warnings.append("One or more source artifacts are missing from the Daily Report inputs.")
    return list(dict.fromkeys(warnings))


def _next_actions(missing: list[dict[str, Any]], allocation_summary: dict[str, Any]) -> list[str]:
    actions = ["Human review required before any paper allocation change."]
    statuses = {str(item.get("status")) for item in missing}
    if "Missing ML Evidence" in statuses:
        actions.append("Collect or link ML evidence before treating recommendations as model-supported.")
    if "Missing Attribution" in statuses:
        actions.append("Collect attribution/decomposition evidence before claiming return source support.")
    if "INSUFFICIENT_HISTORY" in statuses:
        actions.append("Accumulate more paper/shadow observations before treating VaR/CVaR as complete.")
    if allocation_summary.get("daily_recommendation_status") != "AVAILABLE":
        actions.append("Generate or review the daily recommendation artifact.")
    return list(dict.fromkeys(actions))


def daily_report_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def daily_report_artifact_path(root: str | Path, run_id: str) -> Path:
    return daily_report_artifact_dir(root) / f"{run_id}.json"


def latest_daily_report_artifact_path(root: str | Path) -> Path | None:
    return _latest_json_path(daily_report_artifact_dir(root))


def read_latest_daily_report_artifact(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_daily_report_artifact_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "No Daily Report artifact has been generated yet.",
        }
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or payload.get("source") != SOURCE:
        return {
            "ok": False,
            "status": "INVALID_ARTIFACT",
            "source": SOURCE,
            "artifact_path": _relative(root_path, path),
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "Latest Daily Report artifact is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }


def build_daily_report_artifact(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    report_date = generated_at[:10]
    snapshot = load_snapshot_summary_for_response(root_path)
    daily_latest = read_latest_daily_recommendation_artifact(root_path)
    allocation_latest = read_latest_allocation_recommendation_artifact(root_path)
    proposal_latest = read_latest_paper_allocation_proposal(root_path)
    latest_job = read_latest_strategy_factory_job(root_path)
    strategy_payload = build_strategy_intelligence_payload(root_path, now=now)
    latest_risk = read_latest_risk_evidence_artifact(root_path)
    paper_rebalance = paper_rebalance_snapshot_payload(root_path)
    sources = [
        {
            "name": "operational_snapshot_summary",
            "ok": bool(snapshot.get("ok")),
            "status": "AVAILABLE" if snapshot.get("ok") else "MISSING_ARTIFACT",
            "artifact_path": "/api/snapshot-summary",
            "source": snapshot.get("schema_version"),
        },
        _source_record("daily_recommendation", daily_latest),
        _source_record("allocation_recommendation", allocation_latest),
        _source_record("paper_allocation_proposal", proposal_latest),
        _source_record("strategy_factory_selected_batch_job", latest_job),
        {
            "name": "strategy_intelligence",
            "ok": bool(strategy_payload.get("ok")),
            "status": "AVAILABLE" if strategy_payload.get("ok") else "MISSING_ARTIFACT",
            "artifact_path": "/api/strategy-intelligence",
            "source": strategy_payload.get("schema_version"),
        },
        _source_record("risk_evidence", latest_risk),
    ]
    portfolio = _portfolio_summary(snapshot)
    allocation = _allocation_summary(daily_latest, allocation_latest, proposal_latest, paper_rebalance)
    factory = _factory_summary(latest_job)
    intelligence = _strategy_intelligence_summary(strategy_payload)
    risk = _risk_evidence_summary(latest_risk)
    missing = _missing_evidence(sources, intelligence, risk)
    warnings = _warnings(missing, risk)
    labels = list(dict.fromkeys(BASE_LABELS + [str(item.get("status")) for item in missing if item.get("status")]))
    return {
        "ok": True,
        "source": SOURCE,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "report_date": report_date,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "nav_pnl_mutation": False,
        "input_artifacts": sources,
        "portfolio_summary": portfolio,
        "allocation_summary": allocation,
        "strategy_factory_summary": factory,
        "strategy_intelligence_summary": intelligence,
        "risk_evidence_summary": risk,
        "daily_actions": _daily_actions(daily_latest, strategy_payload),
        "missing_evidence": missing,
        "warnings": warnings,
        "next_actions": _next_actions(missing, allocation),
        "labels": labels,
    }


def write_daily_report_artifact(root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_daily_report_artifact(root_path, now=now)
    run_id = payload["generated_at"].replace("+00:00", "Z").replace(":", "").replace("-", "")[:15]
    path = daily_report_artifact_path(root_path, run_id)
    _atomic_write_json(path, payload)
    return {
        "ok": True,
        "status": "GENERATED",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
    }
