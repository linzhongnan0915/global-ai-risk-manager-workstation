"""Lightweight dashboard artifact views for faster initial page load."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def slim_strategy_record(strategy: dict[str, Any]) -> dict[str, Any]:
    """Return a strategy row without drawer-only heavy payloads."""
    slim = {key: value for key, value in strategy.items() if key != "position_packet"}
    risk_packet = slim.get("risk_packet")
    if isinstance(risk_packet, dict):
        slim["risk_packet"] = {key: value for key, value in risk_packet.items() if key != "chart_series"}
    return slim


def build_bootstrap_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Core workstation payload for first paint (Command Center + monitors)."""
    bootstrap = deepcopy(artifact)
    literature = artifact.get("literature_strategy_backtests") or {}
    results = literature.get("results") or []
    bootstrap["literature_strategy_backtests"] = {
        "lazy_load": True,
        "results": [],
        "results_count": len(results),
        "summary": literature.get("summary") or {},
    }
    bootstrap["strategies"] = [slim_strategy_record(strategy) for strategy in artifact.get("strategies") or []]
    bootstrap["artifact_load_profile"] = {
        "mode": "bootstrap",
        "includes_research_backtests": False,
        "includes_strategy_drawer_series": False,
    }
    return bootstrap


def build_research_extension(artifact: dict[str, Any]) -> dict[str, Any]:
    """Research Lab literature backtests loaded after bootstrap."""
    return {
        "literature_strategy_backtests": artifact.get("literature_strategy_backtests") or {},
        "artifact_load_profile": {"mode": "research_extension"},
    }


def build_strategy_detail(artifact: dict[str, Any], strategy_id: str) -> dict[str, Any] | None:
    """Drawer-only strategy payloads fetched on demand."""
    for strategy in artifact.get("strategies") or []:
        if strategy.get("strategy_id") != strategy_id:
            continue
        detail: dict[str, Any] = {"strategy_id": strategy_id}
        if "position_packet" in strategy:
            detail["position_packet"] = strategy["position_packet"]
        chart_series = (strategy.get("risk_packet") or {}).get("chart_series")
        if chart_series:
            detail["risk_packet"] = {"chart_series": chart_series}
        return detail
    return None
