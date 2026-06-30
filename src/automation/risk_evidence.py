"""Risk evidence artifact V0.

Builds a paper/shadow-only risk evidence artifact from existing realized
performance records. Read helpers never create files or mutate financial state.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = "risk_evidence_artifact_v0"
SCHEMA_VERSION = "0.1.0"
ARTIFACT_DIR = Path("data/automation/risk_evidence")
DEFAULT_INPUT_ARTIFACT = Path("dashboard/data/canonical_operational.json")
CONFIDENCE_LEVEL = 0.95
MIN_VAR_OBSERVATIONS = 20
MIN_VOL_OBSERVATIONS = 2
ROLLING_WINDOWS = (5, 20)
BASE_LABELS = ["Prototype Only", "Paper Only", "Institutional Validation Pending"]
MISSING_LABELS = BASE_LABELS + ["Missing Risk Evidence", "Insufficient Risk History"]


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


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dated_return_rows(rows: list[dict[str, Any]], return_key: str) -> list[dict[str, Any]]:
    dated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _safe_float(row.get(return_key))
        date = row.get("date") or row.get("return_end_date")
        if value is None or not date:
            continue
        dated.append(
            {
                "date": str(date),
                "return": value,
                "ending_nav": _safe_float(row.get("ending_nav")),
            }
        )
    return sorted(dated, key=lambda item: item["date"])


def _status_metric(
    name: str,
    *,
    value: float | None,
    status: str,
    observation_count: int,
    min_observations_required: int,
    missing_reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "metric": name,
        "status": status,
        "value": value,
        "observation_count": observation_count,
        "min_observations_required": min_observations_required,
    }
    if missing_reason:
        payload["missing_reason"] = missing_reason
    if extra:
        payload.update(extra)
    return payload


def _insufficient_metric(name: str, observation_count: int, min_required: int, reason: str) -> dict[str, Any]:
    return _status_metric(
        name,
        value=None,
        status="INSUFFICIENT_HISTORY",
        observation_count=observation_count,
        min_observations_required=min_required,
        missing_reason=reason,
    )


def _historical_var_cvar(returns: list[float]) -> tuple[float, float]:
    sorted_returns = sorted(returns)
    tail_count = max(1, math.ceil((len(sorted_returns) * (1.0 - CONFIDENCE_LEVEL)) - 1e-12))
    tail = sorted_returns[:tail_count]
    var_return = tail[-1]
    cvar_return = sum(tail) / len(tail)
    return -var_return, -cvar_return


def _max_drawdown(rows: list[dict[str, Any]]) -> float | None:
    navs = [row["ending_nav"] for row in rows if row.get("ending_nav") is not None and row.get("ending_nav", 0) > 0]
    if len(navs) >= 2:
        peak = navs[0]
        drawdowns: list[float] = []
        for nav in navs:
            peak = max(peak, nav)
            drawdowns.append(nav / peak - 1.0)
        return min(drawdowns)
    returns = [row["return"] for row in rows]
    if len(returns) < 2:
        return None
    curve = 1.0
    peak = 1.0
    drawdowns = []
    for value in returns:
        curve *= 1.0 + value
        peak = max(peak, curve)
        drawdowns.append(curve / peak - 1.0)
    return min(drawdowns)


def _worst_rolling_return(returns: list[float], window: int) -> float | None:
    if len(returns) < window:
        return None
    values: list[float] = []
    for index in range(0, len(returns) - window + 1):
        compounded = 1.0
        for value in returns[index : index + window]:
            compounded *= 1.0 + value
        values.append(compounded - 1.0)
    return min(values) if values else None


def _realized_volatility(returns: list[float]) -> float | None:
    if len(returns) < MIN_VOL_OBSERVATIONS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def compute_risk_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observation_count = len(rows)
    returns = [row["return"] for row in rows]
    reason = (
        f"Only {observation_count} observations are available; "
        f"{MIN_VAR_OBSERVATIONS} are required for historical tail evidence."
    )
    if not rows:
        return {
            "status": "MISSING_DATA",
            "observation_count": 0,
            "metrics": {
                "historical_var_95": _status_metric(
                    "historical_var_95",
                    value=None,
                    status="MISSING_DATA",
                    observation_count=0,
                    min_observations_required=MIN_VAR_OBSERVATIONS,
                    missing_reason="No realized return observations were found.",
                    extra={"confidence_level": CONFIDENCE_LEVEL, "value_description": "positive number means realized loss"},
                ),
                "historical_cvar_95": _status_metric(
                    "historical_cvar_95",
                    value=None,
                    status="MISSING_DATA",
                    observation_count=0,
                    min_observations_required=MIN_VAR_OBSERVATIONS,
                    missing_reason="No realized return observations were found.",
                    extra={"confidence_level": CONFIDENCE_LEVEL, "value_description": "positive number means average realized tail loss"},
                ),
                "max_drawdown": _status_metric(
                    "max_drawdown",
                    value=None,
                    status="MISSING_DATA",
                    observation_count=0,
                    min_observations_required=2,
                    missing_reason="No NAV or return curve was available.",
                ),
            },
            "labels": MISSING_LABELS,
        }
    metrics: dict[str, Any] = {}
    if observation_count >= MIN_VAR_OBSERVATIONS:
        var_loss, cvar_loss = _historical_var_cvar(returns)
        metrics["historical_var_95"] = _status_metric(
            "historical_var_95",
            value=var_loss,
            status="COMPUTED",
            observation_count=observation_count,
            min_observations_required=MIN_VAR_OBSERVATIONS,
            extra={"confidence_level": CONFIDENCE_LEVEL, "value_description": "positive number means realized loss"},
        )
        metrics["historical_cvar_95"] = _status_metric(
            "historical_cvar_95",
            value=cvar_loss,
            status="COMPUTED",
            observation_count=observation_count,
            min_observations_required=MIN_VAR_OBSERVATIONS,
            extra={"confidence_level": CONFIDENCE_LEVEL, "value_description": "positive number means average realized tail loss"},
        )
    else:
        metrics["historical_var_95"] = _insufficient_metric("historical_var_95", observation_count, MIN_VAR_OBSERVATIONS, reason) | {
            "confidence_level": CONFIDENCE_LEVEL,
            "value_description": "positive number means realized loss",
        }
        metrics["historical_cvar_95"] = _insufficient_metric("historical_cvar_95", observation_count, MIN_VAR_OBSERVATIONS, reason) | {
            "confidence_level": CONFIDENCE_LEVEL,
            "value_description": "positive number means average realized tail loss",
        }
    drawdown = _max_drawdown(rows)
    metrics["max_drawdown"] = (
        _status_metric(
            "max_drawdown",
            value=drawdown,
            status="COMPUTED",
            observation_count=observation_count,
            min_observations_required=2,
            extra={"value_description": "negative number means drawdown from running peak"},
        )
        if drawdown is not None
        else _insufficient_metric("max_drawdown", observation_count, 2, "At least two NAV or return observations are required.")
    )
    metrics["worst_1_day_return"] = _status_metric(
        "worst_1_day_return",
        value=min(returns),
        status="COMPUTED",
        observation_count=observation_count,
        min_observations_required=1,
        extra={"value_description": "negative number means realized loss"},
    )
    for window in ROLLING_WINDOWS:
        value = _worst_rolling_return(returns, window)
        metric_name = f"worst_{window}_day_rolling_return"
        metrics[metric_name] = (
            _status_metric(
                metric_name,
                value=value,
                status="COMPUTED",
                observation_count=observation_count,
                min_observations_required=window,
                extra={"value_description": "negative number means compounded realized loss"},
            )
            if value is not None
            else _insufficient_metric(metric_name, observation_count, window, f"At least {window} observations are required.")
        )
    volatility = _realized_volatility(returns)
    metrics["realized_volatility"] = (
        _status_metric(
            "realized_volatility",
            value=volatility,
            status="COMPUTED",
            observation_count=observation_count,
            min_observations_required=MIN_VOL_OBSERVATIONS,
            extra={"annualized": False},
        )
        if volatility is not None
        else _insufficient_metric("realized_volatility", observation_count, MIN_VOL_OBSERVATIONS, "At least two observations are required.")
    )
    insufficient = any(metric.get("status") in {"INSUFFICIENT_HISTORY", "MISSING_DATA"} for metric in metrics.values())
    return {
        "status": "PARTIAL" if insufficient else "COMPUTED",
        "observation_count": observation_count,
        "window_start": rows[0]["date"],
        "window_end": rows[-1]["date"],
        "metrics": metrics,
        "labels": MISSING_LABELS if insufficient else BASE_LABELS,
    }


def _load_input_payload(root: Path) -> tuple[dict[str, Any], list[str], str]:
    path = root / DEFAULT_INPUT_ARTIFACT
    payload = _read_json(path, {})
    if isinstance(payload, dict) and payload:
        return payload, [_relative(root, path)], "canonical_operational"
    return {}, [], "missing_canonical_operational"


def _strategy_evidence(strategy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in strategy_rows:
        if not isinstance(row, dict):
            continue
        strategy_id = row.get("strategy_id")
        if not strategy_id:
            continue
        grouped.setdefault(str(strategy_id), []).append(row)
    evidence = []
    for strategy_id, rows in sorted(grouped.items()):
        dated = _dated_return_rows(rows, "net_return")
        metrics = compute_risk_metrics(dated)
        evidence.append(
            {
                "strategy_uid": strategy_id,
                "status": metrics.get("status"),
                "observation_count": metrics.get("observation_count", 0),
                "window_start": metrics.get("window_start"),
                "window_end": metrics.get("window_end"),
                "risk_metrics": metrics.get("metrics", {}),
                "labels": metrics.get("labels", MISSING_LABELS),
            }
        )
    return evidence


def risk_evidence_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def risk_evidence_artifact_path(root: str | Path, run_id: str) -> Path:
    return risk_evidence_artifact_dir(root) / f"{run_id}.json"


def latest_risk_evidence_artifact_path(root: str | Path) -> Path | None:
    folder = risk_evidence_artifact_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_risk_evidence_artifact(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_risk_evidence_artifact_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "No risk evidence artifact has been generated yet.",
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
            "message": "Latest risk evidence artifact is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }


def build_risk_evidence_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    input_payload: dict[str, Any] | None = None,
    input_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    run_id = generated_at.replace("+00:00", "Z").replace(":", "").replace("-", "")[:15]
    loaded_payload, loaded_artifacts, input_source = _load_input_payload(root_path)
    payload = input_payload if input_payload is not None else loaded_payload
    artifacts = input_artifacts if input_artifacts is not None else loaded_artifacts
    portfolio_rows = payload.get("portfolio_daily") if isinstance(payload, dict) else []
    strategy_rows = payload.get("strategy_daily") if isinstance(payload, dict) else []
    portfolio_dated = _dated_return_rows(portfolio_rows if isinstance(portfolio_rows, list) else [], "daily_return")
    portfolio_metrics = compute_risk_metrics(portfolio_dated)
    missing_data: list[dict[str, Any]] = []
    if not portfolio_dated:
        missing_data.append(
            {
                "scope": "portfolio",
                "status": "MISSING_DATA",
                "missing_reason": "No portfolio daily_return observations were found in the input payload.",
            }
        )
    if len(portfolio_dated) < MIN_VAR_OBSERVATIONS:
        missing_data.append(
            {
                "scope": "portfolio_tail_metrics",
                "status": "INSUFFICIENT_HISTORY",
                "missing_reason": (
                    f"{len(portfolio_dated)} observations found; {MIN_VAR_OBSERVATIONS} are required for historical VaR/CVaR."
                ),
            }
        )
    strategy_evidence = _strategy_evidence(strategy_rows if isinstance(strategy_rows, list) else [])
    if not strategy_evidence:
        missing_data.append(
            {
                "scope": "strategy",
                "status": "MISSING_DATA",
                "missing_reason": "No strategy-level net_return observations were found in the input payload.",
            }
        )
    return {
        "ok": True,
        "source": SOURCE,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "run_id": run_id,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "input_source": input_source if input_payload is None else "provided_payload",
        "input_artifacts": artifacts,
        "observation_count": portfolio_metrics.get("observation_count", 0),
        "window_start": portfolio_metrics.get("window_start"),
        "window_end": portfolio_metrics.get("window_end"),
        "methodology": {
            "return_basis": "historical realized paper/shadow returns only",
            "var_method": "historical empirical lower tail",
            "confidence_level": CONFIDENCE_LEVEL,
            "cvar_method": "average realized loss beyond the historical VaR tail",
            "drawdown_method": "NAV/equity curve when available; otherwise compounded realized returns",
            "annualized": False,
            "min_observations_required": {
                "historical_var_95": MIN_VAR_OBSERVATIONS,
                "historical_cvar_95": MIN_VAR_OBSERVATIONS,
                "max_drawdown": 2,
                "worst_5_day_rolling_return": 5,
                "worst_20_day_rolling_return": 20,
                "realized_volatility": MIN_VOL_OBSERVATIONS,
            },
        },
        "portfolio_risk_evidence": {
            "status": portfolio_metrics.get("status"),
            "risk_metrics": portfolio_metrics.get("metrics", {}),
            "labels": portfolio_metrics.get("labels", MISSING_LABELS),
        },
        "strategy_risk_evidence": strategy_evidence,
        "missing_data": missing_data,
        "labels": portfolio_metrics.get("labels", MISSING_LABELS),
    }


def write_risk_evidence_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    input_payload: dict[str, Any] | None = None,
    input_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_risk_evidence_artifact(
        root_path,
        now=now,
        input_payload=input_payload,
        input_artifacts=input_artifacts,
    )
    path = risk_evidence_artifact_path(root_path, payload["run_id"])
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
