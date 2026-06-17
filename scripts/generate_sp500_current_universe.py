"""Generate the current S&P 500 reference universe artifact.

This artifact is benchmark/reference data only. It is not a historical
constituent set and must not be used to migrate strategies or allocations.
"""

from __future__ import annotations

import argparse
import json
from io import StringIO
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "dashboard" / "data" / "universes" / "sp500_current.json"
DEFAULT_SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SURVIVORSHIP_WARNING = (
    "Current S&P 500 reference universe only; not historical constituent-corrected "
    "and not valid for strict historical backtests without survivorship-bias controls."
)


def _clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_constituents(frame: pd.DataFrame, *, source_url: str, as_of_date: str) -> list[dict[str, Any]]:
    required = {"Symbol", "Security", "GICS Sector", "GICS Sub-Industry"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"S&P 500 source missing required columns: {sorted(missing)}")
    rows = []
    for _, row in frame.iterrows():
        ticker = _clean_text(row.get("Symbol"))
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker.replace(".", "-").upper(),
                "company_name": _clean_text(row.get("Security")),
                "sector": _clean_text(row.get("GICS Sector")),
                "industry": _clean_text(row.get("GICS Sub-Industry")),
                "source": source_url,
                "provider": "Wikipedia",
                "as_of_date": as_of_date,
                "current_constituent": True,
            }
        )
    return sorted(rows, key=lambda item: item["ticker"])


def fetch_sp500_constituents(source_url: str = DEFAULT_SOURCE_URL) -> list[dict[str, Any]]:
    request = Request(
        source_url,
        headers={"User-Agent": "RiskManagerWorkstation/1.0 reference-data-generator"},
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")
    tables = pd.read_html(StringIO(html))
    if not tables:
        raise RuntimeError(f"No tables found at {source_url}")
    return normalize_constituents(tables[0], source_url=source_url, as_of_date=date.today().isoformat())


def build_artifact(constituents: list[dict[str, Any]], *, source_url: str, generated_at: str | None = None) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    as_of_date = constituents[0]["as_of_date"] if constituents else date.today().isoformat()
    return {
        "metadata": {
            "provider": "Wikipedia",
            "source_url": source_url,
            "source_name": "Wikipedia: List of S&P 500 companies",
            "as_of_date": as_of_date,
            "generated_at": generated,
            "current_constituent_count": len(constituents),
            "survivorship_bias_warning": SURVIVORSHIP_WARNING,
        },
        "provider": "Wikipedia",
        "source": source_url,
        "source_url": source_url,
        "as_of_date": as_of_date,
        "generated_at": generated,
        "survivorship_bias_warning": SURVIVORSHIP_WARNING,
        "constituents": constituents,
    }


def write_artifact(artifact: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate current S&P 500 reference universe JSON.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    constituents = fetch_sp500_constituents(args.source_url)
    artifact = build_artifact(constituents, source_url=args.source_url)
    write_artifact(artifact, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "provider": artifact["metadata"]["provider"],
                "current_constituent_count": artifact["metadata"]["current_constituent_count"],
                "as_of_date": artifact["metadata"]["as_of_date"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
