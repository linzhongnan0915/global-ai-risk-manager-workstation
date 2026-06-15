"""Lightweight live data refresh for market, news, and dashboard overlay."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.market.api_client import load_market_snapshot, summarize_market_risk
from src.market.yfinance_client import build_market_snapshot, refresh_yfinance_market_data
from src.news.live_news import refresh_live_news_snapshot
from src.news.news_analyzer import analyze_news_risk, load_news_snapshot
from src.risk.recommendation_engine import build_recommendations


def quick_refresh_market_and_news(
    years: int | None = 2,
    skip_price_history: bool = False,
) -> dict[str, Any]:
    """Refresh market snapshot and news without rebuilding the full dashboard artifact."""
    if skip_price_history and Path("data/processed/market_price_history.csv").exists():
        market_snapshot = build_market_snapshot()
    else:
        try:
            market_snapshot = refresh_yfinance_market_data(years=years)
        except Exception:
            market_snapshot = load_market_snapshot()
    news_snapshot = refresh_live_news_snapshot()
    market_summary = summarize_market_risk(market_snapshot)
    news_risk = analyze_news_risk(news_snapshot)
    return {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "market_snapshot": market_snapshot,
        "market_monitor": market_summary,
        "news_snapshot": news_snapshot,
        "news_risk": news_risk,
        "data_mode": "yfinance_live",
    }


def build_live_overlay(
    artifact: dict[str, Any],
    market_summary: list[dict[str, Any]] | None = None,
    news_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_summary = market_summary if market_summary is not None else artifact.get("market_monitor", [])
    news_risk = news_risk if news_risk is not None else artifact.get("news_risk", {})
    factor_checks = [
        check
        for check in (artifact.get("risk_limits", {}).get("factors", {}).get("checks") or [])
        if check.get("status") in {"watch", "warning", "breach"}
    ]
    portfolio_checks = [
        check
        for check in (artifact.get("risk_limits", {}).get("checks") or [])
        if check.get("status") in {"watch", "warning", "breach"}
    ]
    recommendations = build_recommendations(
        market_summary,
        news_risk,
        {
            "estimated_transaction_cost": artifact.get("allocation", {}).get("estimated_transaction_cost"),
            "approval_required": artifact.get("allocation", {}).get("approval_required", True),
            "rationale": artifact.get("allocation", {}).get("rationale", ""),
        },
        factor_checks=factor_checks,
        portfolio_limit_checks=portfolio_checks,
        factor_exposure=artifact.get("factors", {}).get("portfolio_factor_exposure_current", {}),
    )
    market_as_of = None
    if market_summary:
        market_as_of = artifact.get("data_quality", {}).get("latest_strategy_end")
    snapshot_path = Path("output/market_snapshot.json")
    if snapshot_path.exists():
        market_as_of = json.loads(snapshot_path.read_text(encoding="utf-8")).get("as_of", market_as_of)
    return {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "data_mode": "yfinance_live",
        "market_as_of": market_as_of,
        "market_monitor": market_summary,
        "news_risk": news_risk,
        "recommendations": recommendations,
        "factor_exposure_current": artifact.get("factors", {}).get("portfolio_factor_exposure_current", {}),
        "factor_alerts": artifact.get("factors", {}).get("human_review_alerts", []),
        "system_conclusion": artifact.get("decision_review", {}).get("final_decision"),
    }


def write_live_overlay(
    artifact: dict[str, Any],
    output_path: str | Path = "output/live_overlay.json",
    refresh_market: bool = True,
) -> dict[str, Any]:
    if refresh_market:
        try:
            quick = quick_refresh_market_and_news(skip_price_history=True)
            overlay = build_live_overlay(artifact, quick["market_monitor"], quick["news_risk"])
            overlay["data_mode"] = quick["data_mode"]
            overlay["market_as_of"] = quick["market_snapshot"].get("as_of")
        except Exception:
            overlay = build_live_overlay(artifact)
            overlay["data_mode"] = "artifact_fallback"
    else:
        news_snapshot = load_news_snapshot()
        overlay = build_live_overlay(artifact, artifact.get("market_monitor"), analyze_news_risk(news_snapshot))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay, indent=2), encoding="utf-8")
    return overlay
