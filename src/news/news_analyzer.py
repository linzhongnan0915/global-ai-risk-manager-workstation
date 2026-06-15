"""News ingestion and risk interpretation skeleton."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.market.api_client import fetch_json_api


SEVERITY_SCORE = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def load_news_snapshot(
    sample_path: str | Path = "data/samples/mock_news_snapshot.json",
    raw_output_path: str | Path = "data/raw/latest_news_snapshot.json",
) -> dict[str, Any]:
    endpoint = os.getenv("RMP_NEWS_API_URL")
    api_key = os.getenv("RMP_NEWS_API_KEY")
    if endpoint:
        payload = fetch_json_api(endpoint, api_key)
        Path(raw_output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(raw_output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    live_path = Path(raw_output_path)
    if live_path.exists():
        return json.loads(live_path.read_text(encoding="utf-8"))
    return json.loads(Path(sample_path).read_text(encoding="utf-8"))


def analyze_news_risk(snapshot: dict[str, Any]) -> dict[str, Any]:
    items = snapshot.get("items") or snapshot.get("news") or snapshot.get("articles") or []
    normalized = []
    total_score = 0
    for item in items:
        severity = str(item.get("severity", "low")).lower()
        score = SEVERITY_SCORE.get(severity, 1)
        total_score += score
        normalized.append(
            {
                "headline": item.get("headline") or item.get("title", "Untitled news item"),
                "topic": item.get("topic", "general"),
                "severity": severity,
                "severity_score": score,
                "affected_factors": item.get("affected_factors", []),
                "risk_interpretation": item.get("risk_interpretation", "Review required."),
                "human_review": score >= 3,
            }
        )
    if total_score >= 8:
        watch_level = "urgent_review"
    elif total_score >= 4:
        watch_level = "watch"
    else:
        watch_level = "normal"
    return {
        "watch_level": watch_level,
        "news_risk_score": total_score,
        "items": normalized,
    }

