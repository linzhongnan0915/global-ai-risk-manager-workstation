"""Build a compact static US-equity research bundle for dashboard deployment."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
BUNDLE_PATH = PROJECT_ROOT / "dashboard" / "data" / "us_equity_research_bundle.json"


def _compact_item(item: dict) -> dict:
    backtest = item["backtest"]
    series = backtest["return_series"]
    series["gross_returns"] = [round(float(v), 6) for v in series["gross_returns"]]
    series["net_returns"] = [round(float(v), 6) for v in series["net_returns"]]
    series.pop("dates", None)
    packet = backtest.get("risk_packet") or {}
    chart = packet.get("chart_series") or {}
    backtest["risk_packet"] = {
        "summary_statistics": packet.get("summary_statistics") or {},
        "drawdown_behavior": packet.get("drawdown_behavior") or {},
        "chart_series": {
            "drawdown": chart.get("drawdown") or [],
            "rolling_63d_sharpe": chart.get("rolling_63d_sharpe") or chart.get("rolling_sharpe") or [],
        },
    }
    factory = backtest.get("factory_research") or {}
    factory.pop("screening_report_path", None)
    factory.pop("artifacts_present", None)
    return item


def build_bundle(project_root: Path = PROJECT_ROOT) -> dict:
    from src.reporting.strategy_factory_research_adapter import COMPOSITE_ID, RAPID_BACKTEST_IDS, build_factory_research_catalog

    catalog = build_factory_research_catalog(project_root)
    results = catalog.get("results") or []
    expected_count = len(RAPID_BACKTEST_IDS) + 1
    if len(results) != expected_count:
        raise RuntimeError(f"Expected {expected_count} strategies, found {len(results)}")
    ids = [row.get("strategy_id") for row in results]
    expected_ids = list(RAPID_BACKTEST_IDS) + [COMPOSITE_ID]
    if ids != expected_ids:
        raise RuntimeError(f"Unexpected strategy order/ids: {ids}")
    shared_dates = results[0]["backtest"]["return_series"].get("dates") or []
    if not shared_dates:
        raise RuntimeError("Missing shared return dates in factory catalog")
    compact_results = [_compact_item(row) for row in results]
    return {
        "bundle_version": 2,
        "shared_dates": shared_dates,
        "factory_strategy_research": {
            "source": "us_equity_dashboard_bundle_v2",
            "default_strategy_id": catalog.get("default_strategy_id"),
            "architecture": catalog.get("architecture") or {},
            "groups": catalog.get("groups") or [],
            "results": compact_results,
            "results_count": len(compact_results),
        },
    }


def main() -> int:
    bundle = build_bundle()
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    size_mb = BUNDLE_PATH.stat().st_size / 1_000_000
    print(f"Wrote {BUNDLE_PATH} ({size_mb:.2f} MB, {bundle['factory_strategy_research']['results_count']} strategies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
