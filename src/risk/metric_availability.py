"""Operating-period metric availability guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.risk.engine import portfolio_risk_summary

DEFAULT_CONFIG_PATH = "data/config/metric_availability.yaml"


def load_metric_availability(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"metric availability config not found: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return payload.get("metric_availability", {})


def minimum_observations(metric_name: str, config: dict[str, Any] | None = None) -> int:
    thresholds = config or load_metric_availability()
    entry = thresholds.get(metric_name, {})
    return int(entry.get("minimum_observations", 1))


def wrap_metric(
    value: float | None,
    metric_name: str,
    observations: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach availability metadata to a scalar metric."""

    minimum = minimum_observations(metric_name, config)
    if observations < minimum or value is None:
        return {
            "value": None,
            "available": False,
            "observations": int(observations),
            "minimum_observations": minimum,
            "availability_status": "insufficient",
            "reason": "Insufficient operating-period observations",
        }
    return {
        "value": float(value),
        "available": True,
        "observations": int(observations),
        "minimum_observations": minimum,
        "availability_status": "available",
        "reason": None,
    }


def build_operating_period_risk(
    strategy_returns: dict[str, list[float]],
    weights: dict[str, float],
    *,
    observations: int,
    start_date: str | None,
    end_date: str | None,
    daily_return: float | None = None,
    cumulative_return: float | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build operating-period metrics with availability guards."""

    thresholds = config or load_metric_availability()
    raw: dict[str, float] = {}
    if observations >= minimum_observations("max_drawdown", thresholds):
        try:
            raw = portfolio_risk_summary(strategy_returns, weights, allow_residual_cash=True)
        except ValueError:
            raw = {}

    return {
        "observations": int(observations),
        "start_date": start_date,
        "end_date": end_date,
        "metrics": {
            "portfolio_sharpe": wrap_metric(
                raw.get("portfolio_sharpe") if observations >= 2 else None,
                "sharpe",
                observations,
                thresholds,
            ),
            "portfolio_volatility": wrap_metric(
                raw.get("portfolio_volatility") if observations >= 2 else None,
                "annualized_volatility",
                observations,
                thresholds,
            ),
            "portfolio_var_99": wrap_metric(
                raw.get("portfolio_var_99") if observations >= 2 else None,
                "historical_var_99",
                observations,
                thresholds,
            ),
            "portfolio_expected_shortfall_95": wrap_metric(
                raw.get("portfolio_expected_shortfall_95") if observations >= 2 else None,
                "historical_es_95",
                observations,
                thresholds,
            ),
            "portfolio_max_drawdown": wrap_metric(
                raw.get("portfolio_max_drawdown") if observations >= 2 else None,
                "max_drawdown",
                observations,
                thresholds,
            ),
        },
        "pnl": {
            "daily_return": wrap_metric(daily_return, "daily_return", observations, thresholds),
            "cumulative_return": wrap_metric(cumulative_return, "cumulative_return", observations, thresholds),
        },
        "label": "Operating-period model portfolio risk (not live fills)",
    }


def metric_value(metric: dict[str, Any] | float | None) -> float | None:
    if isinstance(metric, dict):
        return metric.get("value") if metric.get("available") else None
    return float(metric) if metric is not None else None


def format_metric_display(metric: dict[str, Any] | float | None, *, pct_digits: int = 2) -> str:
    if isinstance(metric, dict):
        if not metric.get("available"):
            return "N/A"
        value = metric.get("value")
        if value is None:
            return "N/A"
        if "return" in str(metric.get("metric_name", "")) or abs(value) <= 1.5:
            return f"{100 * float(value):.{pct_digits}f}%"
        return f"{float(value):.2f}"
    if metric is None:
        return "N/A"
    return f"{float(metric):.2f}"
