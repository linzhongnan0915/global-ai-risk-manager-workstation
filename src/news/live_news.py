"""Live news ingestion from yfinance with market-move fallback headlines."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NEWS_TICKERS = ["SPY", "QQQ", "TLT", "HYG", "UUP", "GLD", "DBC", "^VIX"]
TOPIC_BY_KEYWORD = {
    "fed": "central_bank",
    "rate": "central_bank",
    "inflation": "inflation",
    "cpi": "inflation",
    "credit": "credit",
    "spread": "credit",
    "oil": "geopolitical",
    "war": "geopolitical",
    "china": "geopolitical",
    "earnings": "equity",
    "gdp": "macro",
    "jobs": "macro",
    "treasury": "rates",
    "yield": "rates",
}


def _topic_from_text(text: str, bucket: str = "") -> str:
    bucket_map = {
        "equity_beta": "equity",
        "growth_equity": "equity",
        "small_cap": "equity",
        "style_factor": "equity",
        "rates_duration": "rates",
        "credit": "credit",
        "commodity": "geopolitical",
        "usd_fx": "macro",
    }
    if bucket in bucket_map:
        return bucket_map[bucket]
    lowered = text.lower()
    for keyword, topic in TOPIC_BY_KEYWORD.items():
        if keyword in lowered:
            return topic
    return "general"


def _severity_from_text(text: str) -> str:
    lowered = text.lower()
    critical_words = ("crash", "crisis", "default", "war", "emergency", "collapse")
    high_words = ("surge", "plunge", "selloff", "bankruptcy", "downgrade", "recession")
    medium_words = ("rise", "fall", "cut", "hike", "warning", "concern", "pressure")
    if any(word in lowered for word in critical_words):
        return "high"
    if any(word in lowered for word in high_words):
        return "high"
    if any(word in lowered for word in medium_words):
        return "medium"
    return "low"


def _affected_factors(topic: str, text: str) -> list[str]:
    mapping = {
        "central_bank": ["Rates Duration", "Equity Beta", "USD"],
        "inflation": ["Commodity", "Rates Duration", "Inflation"],
        "credit": ["Credit Spread", "Liquidity"],
        "geopolitical": ["Commodity", "Geopolitical Risk", "USD"],
        "equity": ["Equity Beta", "Growth Equity"],
        "macro": ["Equity Beta", "Rates Duration", "Credit Spread"],
        "rates": ["Rates Duration", "Real Yields"],
    }
    factors = list(mapping.get(topic, ["Equity Beta"]))
    lowered = text.lower()
    if "vix" in lowered or "volatility" in lowered:
        factors.append("Volatility")
    return factors[:4]


def _interpret_headline(headline: str, topic: str) -> str:
    templates = {
        "central_bank": "Policy path affects duration, equity multiples, and USD risk.",
        "inflation": "Inflation narrative drives rates, commodities, and real-yield sensitivity.",
        "credit": "Credit headline may affect spread risk and liquidity appetite.",
        "geopolitical": "Geopolitical supply or risk headline — review commodity and safe-haven sleeves.",
        "equity": "Equity headline may affect beta and factor concentration.",
        "macro": "Macro release may shift growth/inflation regime assumptions.",
        "rates": "Rates headline affects duration sleeves and curve-sensitive strategies.",
    }
    base = templates.get(topic, "Review portfolio factor exposure and scenario shocks.")
    return f"{base} Headline: {headline[:140]}"


def headlines_from_market_moves(market_snapshot: dict[str, Any], threshold: float = 0.012) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in market_snapshot.get("markets", []):
        daily_return = float(row.get("daily_return") or 0.0)
        if abs(daily_return) < threshold:
            continue
        ticker = str(row.get("ticker", "MARKET"))
        direction = "rose" if daily_return > 0 else "fell"
        headline = f"{ticker} {direction} {abs(daily_return):.1%} in latest session"
        topic = _topic_from_text(f"{ticker} {row.get('bucket', '')} {row.get('risk_interpretation', '')}", str(row.get("bucket", "")))
        severity = "high" if abs(daily_return) >= 0.025 else "medium"
        items.append(
            {
                "headline": headline,
                "topic": topic,
                "severity": severity,
                "affected_factors": _affected_factors(topic, headline),
                "risk_interpretation": row.get("risk_interpretation") or _interpret_headline(headline, topic),
                "source": "market_move_proxy",
                "publisher": "yfinance_market_snapshot",
            }
        )
    return items


def fetch_yfinance_news(max_items: int = 12) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError:
        return []

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for ticker in NEWS_TICKERS:
        try:
            news_rows = yf.Ticker(ticker).news or []
        except Exception:
            continue
        for row in news_rows[:3]:
            content = row.get("content") or {}
            title = content.get("title") or row.get("title")
            if not title or title in seen:
                continue
            seen.add(title)
            summary = content.get("summary") or row.get("summary") or ""
            topic = _topic_from_text(f"{title} {summary}")
            severity = _severity_from_text(f"{title} {summary}")
            items.append(
                {
                    "headline": title,
                    "topic": topic,
                    "severity": severity,
                    "affected_factors": _affected_factors(topic, f"{title} {summary}"),
                    "risk_interpretation": _interpret_headline(title, topic),
                    "source": "yfinance_news",
                    "publisher": content.get("provider", {}).get("displayName") or row.get("publisher", ticker),
                    "published_at": content.get("pubDate") or row.get("providerPublishTime"),
                    "link": content.get("canonicalUrl") or content.get("clickThroughUrl") or row.get("link"),
                }
            )
            if len(items) >= max_items:
                return items
    return items


def build_live_news_snapshot(
    market_snapshot: dict[str, Any] | None = None,
    max_items: int = 12,
) -> dict[str, Any]:
    market_snapshot = market_snapshot or {}
    news_items = fetch_yfinance_news(max_items=max_items)
    if not news_items and market_snapshot:
        news_items = headlines_from_market_moves(market_snapshot)
    elif market_snapshot:
        move_items = headlines_from_market_moves(market_snapshot, threshold=0.018)
        existing = {item["headline"] for item in news_items}
        for item in move_items:
            if item["headline"] not in existing:
                news_items.append(item)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance_live" if news_items else "market_move_fallback",
        "items": news_items[:max_items],
    }


def refresh_live_news_snapshot(
    market_snapshot_path: str | Path = "output/market_snapshot.json",
    output_path: str | Path = "data/raw/latest_news_snapshot.json",
) -> dict[str, Any]:
    market_snapshot: dict[str, Any] = {}
    path = Path(market_snapshot_path)
    if path.exists():
        market_snapshot = json.loads(path.read_text(encoding="utf-8"))
    payload = build_live_news_snapshot(market_snapshot)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
