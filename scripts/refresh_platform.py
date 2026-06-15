"""Refresh market/news snapshots, risk recommendations, and dashboard artifact."""

from pathlib import Path
import json
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.artifact_generator import generate_dashboard_artifact
from src.market.yfinance_client import refresh_yfinance_market_data
from scripts.run_replication_clone import main as run_replication_clone
from scripts.run_literature_strategy_backtests import main as run_literature_strategy_backtests
from scripts.export_strategy_decision_tables import main as export_strategy_decision_tables
from scripts.audit_dashboard_data_contract import main as audit_dashboard_data_contract


def main() -> None:
    if not os.getenv("RMP_MARKET_API_URL"):
        try:
            snapshot = refresh_yfinance_market_data()
            print(f"Refreshed yfinance market data: {snapshot['as_of']} ({len(snapshot['markets'])} tickers)")
        except Exception as exc:
            print(f"WARNING: yfinance refresh failed; using latest snapshot or sample data. {exc}")

    try:
        run_replication_clone()
    except Exception as exc:
        print(f"WARNING: replication clone refresh failed; using latest snapshot if available. {exc}")

    try:
        run_literature_strategy_backtests()
    except Exception as exc:
        print(f"WARNING: literature strategy backtests failed; using latest snapshot if available. {exc}")

    artifact = generate_dashboard_artifact(
        PROJECT_ROOT / "data/config/strategy_registry.json",
        PROJECT_ROOT / "output/dashboard_artifact.json",
    )
    recommendation_path = PROJECT_ROOT / "output/risk_recommendation_snapshot.json"
    recommendation_path.write_text(
        json.dumps(
            {
                "as_of_date": artifact["as_of_date"],
                "market_monitor": artifact["market_monitor"],
                "news_risk": artifact["news_risk"],
                "recommendations": artifact["recommendations"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    export_strategy_decision_tables()
    audit_dashboard_data_contract()
    try:
        from src.market.live_refresh import write_live_overlay

        write_live_overlay(artifact, refresh_market=False)
        print(f"Refreshed live overlay: {PROJECT_ROOT / 'output/live_overlay.json'}")
    except Exception as exc:
        print(f"WARNING: live overlay refresh failed. {exc}")
    print(f"Refreshed dashboard artifact: {PROJECT_ROOT / 'output/dashboard_artifact.json'}")
    print(f"Refreshed recommendation snapshot: {recommendation_path}")


if __name__ == "__main__":
    main()
