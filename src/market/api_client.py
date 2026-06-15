"""Market data API adapter skeleton.

The platform can run from sample snapshots now and switch to a boss-provided
API later by setting environment variables in `platform_config.yaml`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def fetch_json_api(endpoint: str, api_key: str | None = None, timeout_seconds: int = 20) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, headers=headers)
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def load_market_snapshot(
    sample_path: str | Path = "data/samples/mock_market_snapshot.json",
    raw_output_path: str | Path = "data/raw/latest_market_snapshot.json",
    yfinance_snapshot_path: str | Path = "output/market_snapshot.json",
) -> dict[str, Any]:
    endpoint = os.getenv("RMP_MARKET_API_URL")
    api_key = os.getenv("RMP_MARKET_API_KEY")
    if endpoint:
        payload = fetch_json_api(endpoint, api_key)
        Path(raw_output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(raw_output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    if Path(yfinance_snapshot_path).exists():
        return json.loads(Path(yfinance_snapshot_path).read_text(encoding="utf-8"))
    return json.loads(Path(sample_path).read_text(encoding="utf-8"))


def summarize_market_risk(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = snapshot.get("markets", [])
    summary = []
    for row in rows:
        daily_return = float(row.get("daily_return", 0.0))
        if daily_return <= -0.015:
            status = "warning"
        elif daily_return >= 0.015:
            status = "watch"
        else:
            status = "normal"
        summary.append(
            {
                "ticker": row.get("ticker"),
                "name": row.get("name", row.get("ticker")),
                "last": row.get("last"),
                "daily_return": daily_return,
                "status": status,
                "risk_interpretation": row.get("risk_interpretation", "No interpretation supplied."),
            }
        )
    return summary
