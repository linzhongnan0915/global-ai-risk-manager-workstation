"""Validate configs, registry, artifacts, and documentation contracts."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.registry import load_strategy_registry, registry_weights


def assert_file(path: str) -> Path:
    resolved = PROJECT_ROOT / path
    if not resolved.exists():
        raise AssertionError(f"Missing required file: {path}")
    return resolved


def main() -> None:
    required_files = [
        "README.md",
        "docs/strategy_intake_workflow.md",
        "docs/workstation_ui_reference_contract.md",
        "docs/dashboard_data_contract_audit.md",
        "docs/institutional_decision_workflow.md",
        "docs/workflows/risk_manager_platform_workflow.md",
        "data/config/platform_config.yaml",
        "data/config/risk_limits.yaml",
        "data/config/allocation_policy.yaml",
        "data/config/decision_governance.yaml",
        "data/config/workstation_ui_contract.json",
        "data/config/strategy_registry.json",
        "output/dashboard_artifact.json",
        "output/contract_audit/dashboard_data_contract_audit.json",
        "output/workflows/risk_manager_platform_workflow.html",
        "output/workflows/risk_manager_platform_workflow.png",
        "output/risk_recommendation_snapshot.json",
        "dashboard/index.html",
        "dashboard/styles.css",
        "dashboard/app.js",
    ]
    for path in required_files:
        assert_file(path)

    for path in [
        "data/config/platform_config.yaml",
        "data/config/risk_limits.yaml",
        "data/config/allocation_policy.yaml",
        "data/config/decision_governance.yaml",
    ]:
        with assert_file(path).open("r", encoding="utf-8") as file:
            yaml.safe_load(file)

    records = load_strategy_registry(assert_file("data/config/strategy_registry.json"))
    weights = registry_weights(records)
    if len(records) < 20:
        raise AssertionError("Strategy registry must include at least 20 strategies.")
    if abs(sum(weights.values()) - 1.0) > 1e-8:
        raise AssertionError("Strategy registry weights must sum to 1.0.")
    for record in records:
        if not record.raw.get("failure_modes"):
            raise AssertionError(f"Strategy {record.strategy_id} is missing failure modes.")
        if record.raw.get("transaction_cost_bps_buy") != 5 or record.raw.get("transaction_cost_bps_sell") != 5:
            raise AssertionError(f"Strategy {record.strategy_id} must use 5 bps buy/sell costs.")

    dashboard_artifact = json.loads(assert_file("output/dashboard_artifact.json").read_text(encoding="utf-8"))
    recommendation_artifact = json.loads(assert_file("output/risk_recommendation_snapshot.json").read_text(encoding="utf-8"))
    ui_contract = json.loads(assert_file("data/config/workstation_ui_contract.json").read_text(encoding="utf-8"))
    if dashboard_artifact["strategy_count"] != len(records):
        raise AssertionError("Dashboard artifact strategy_count does not match registry.")
    if "recommendations" not in dashboard_artifact:
        raise AssertionError("Dashboard artifact missing recommendations.")
    if "ui_contract" not in dashboard_artifact:
        raise AssertionError("Dashboard artifact missing workstation UI contract.")
    if len(ui_contract.get("shell", {}).get("primary_tabs", [])) != 9:
        raise AssertionError("Workstation UI contract must define exactly 9 primary workflow tabs.")
    if ui_contract.get("visual_language", {}).get("product_type") != "hedge_fund_asset_manager_risk_workstation":
        raise AssertionError("Workstation UI contract product_type must remain institutional risk workstation.")
    if "news_risk" not in recommendation_artifact:
        raise AssertionError("Recommendation snapshot missing news_risk.")

    print("Framework validation passed.")
    print(f"Strategies: {len(records)}")
    print(f"Weight sum: {sum(weights.values()):.6f}")
    print(f"Dashboard artifact date: {dashboard_artifact['as_of_date']}")


if __name__ == "__main__":
    main()
