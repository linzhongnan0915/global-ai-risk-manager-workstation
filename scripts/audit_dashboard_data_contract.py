"""Audit dashboard artifact coverage against workstation UI/data contracts."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


TOP_LEVEL_ALIASES = {
    "metadata": ["as_of_date", "initial_capital", "strategy_count", "strategy_return_source"],
    "portfolio": ["risk_summary", "portfolio_series"],
    "market_macro": ["market_monitor"],
    "news_event_risk": ["news_risk"],
    "backtesting_research": ["literature_strategy_backtests"],
    "decision_log": ["daily_decision_log"],
    "decision_review": ["decision_review"],
    "decision_workflow": ["decision_workflow"],
}

STRATEGY_FIELD_ALIASES = {
    "daily_return": ["proxy_metrics.daily_return"],
    "sharpe": ["net_metrics.sharpe", "proxy_metrics.proxy_sharpe"],
    "volatility": ["net_metrics.annual_volatility", "proxy_metrics.proxy_volatility"],
    "max_drawdown": ["net_metrics.max_drawdown", "proxy_metrics.proxy_max_drawdown"],
    "current_drawdown": ["risk_packet.drawdown_behavior.current_drawdown"],
    "win_rate": ["net_metrics.win_rate", "risk_packet.summary_statistics.win_rate"],
    "turnover": ["turnover.annualized_turnover"],
    "transaction_cost_drag": ["turnover.annualized_cost_drag"],
    "signal_status": ["signal_summary"],
    "correlation_warning": ["correlation_gate.reason_code"],
    "factor_exposure_summary": ["factor_exposure.concentration.top_factor"],
    "signal_state": ["signal_summary"],
    "data_quality_status": ["backtest_evidence.status"],
    "cumulative_pnl": ["net_metrics.cumulative_return"],
}

DETAIL_SECTION_ALIASES = {
    "performance_chart": ["risk_packet.chart_series.cumulative_return"],
    "drawdown_chart": ["risk_packet.chart_series.drawdown"],
    "signal_history": ["position_packet.signal_history"],
    "position_history": ["position_packet.position_history"],
    "backtest_summary": ["backtest_evidence", "net_metrics"],
    "walk_forward_results": ["walk_forward"],
    "factor_exposure": ["factor_exposure"],
    "current_risk_explanation": ["risk_manager_question_answered"],
    "failure_modes": ["failure_modes"],
    "human_review_note": ["trade_decision"],
    "summary_statistics": ["risk_packet.summary_statistics"],
    "distribution_shape": ["risk_packet.distribution_shape"],
    "tail_risk": ["risk_packet.tail_risk"],
    "drawdown_behavior": ["risk_packet.drawdown_behavior"],
    "time_stability": ["risk_packet.time_stability"],
    "regime_breakdown": ["risk_packet.regime_breakdown"],
    "benchmark_comparison": ["risk_packet.comparison_vs_benchmark"],
    "transaction_cost": ["turnover", "rebalance_trade"],
    "decision_packet": ["trade_decision", "recommended_action", "risk_limit_checks"],
}

ALLOCATION_ALIASES = {
    "risk_before_after": ["before_after", "risk_before", "risk_after"],
    "buy_sell_direction": ["rebalance_trade_list"],
    "dollar_amount": ["rebalance_trade_list"],
    "human_approval_status": ["human_approval_required", "approval_required"],
}

MODULE_DATA_ALIASES = {
    "current_weights": ["allocation.current_weights"],
    "proposed_weights": ["allocation.proposed_weights"],
    "weight_changes": ["allocation.weight_changes"],
    "buy_sell_direction": ["allocation.rebalance_trade_list"],
    "dollar_amount": ["allocation.rebalance_trade_list"],
    "estimated_transaction_cost": ["allocation.estimated_transaction_cost"],
    "factor_exposure": ["factors"],
    "factor_concentration_before_after": ["allocation.factor_concentration_before_after"],
    "correlation_before_after": ["allocation.correlation_before_after"],
    "human_approval_status": ["allocation.human_approval_required", "allocation.approval_required"],
    "risk_before_after": ["allocation.before_after", "allocation.risk_before", "allocation.risk_after"],
}


def main() -> None:
    artifact = _load_json("output/dashboard_artifact.json")
    ui_contract = _load_json("data/config/workstation_ui_contract.json")
    data_contract = _load_json("data/config/dashboard_artifact_contract.json")

    report = {
        "audit_version": "0.1.0",
        "artifact_path": "output/dashboard_artifact.json",
        "as_of_date": artifact.get("as_of_date"),
        "strategy_count": artifact.get("strategy_count"),
        "summary": {},
        "top_level_sections": _audit_top_level_sections(artifact, data_contract),
        "modules": _audit_modules(artifact, ui_contract),
        "strategy_table": _audit_strategy_rows(artifact, ui_contract, data_contract),
        "strategy_drilldown": _audit_strategy_drilldown(artifact, ui_contract, data_contract),
        "allocation": _audit_allocation(artifact, data_contract),
        "priority_gaps": [],
    }
    report["priority_gaps"] = _priority_gaps(report)
    report["summary"] = _summary(report)

    output_dir = PROJECT_ROOT / "output/contract_audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dashboard_data_contract_audit.json"
    md_path = PROJECT_ROOT / "docs/dashboard_data_contract_audit.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Coverage: {report['summary']['overall_coverage']:.1%}")
    if report["priority_gaps"]:
        print("Priority gaps:")
        for gap in report["priority_gaps"][:8]:
            print(f"- {gap['severity']}: {gap['item']} ({gap['reason']})")


def _load_json(path: str) -> dict:
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))


def _audit_top_level_sections(artifact: dict, data_contract: dict) -> list[dict]:
    rows = []
    for section in data_contract.get("top_level_sections", []):
        paths = TOP_LEVEL_ALIASES.get(section, [section])
        present = any(_has_path(artifact, path) for path in paths)
        rows.append({"section": section, "present": present, "artifact_paths_checked": paths})
    return rows


def _audit_modules(artifact: dict, ui_contract: dict) -> list[dict]:
    rows = []
    for module, spec in ui_contract.get("modules", {}).items():
        required = spec.get("required_data", [])
        missing = []
        present = []
        for field in required:
            paths = MODULE_DATA_ALIASES.get(field, [field])
            if any(_has_path(artifact, path) for path in paths):
                present.append(field)
            else:
                missing.append(field)
        rows.append(
            {
                "module": module,
                "required_components": spec.get("required_components", []),
                "required_data_count": len(required),
                "present_data": present,
                "missing_data": missing,
                "coverage": _coverage(len(present), len(required)),
            }
        )
    return rows


def _audit_strategy_rows(artifact: dict, ui_contract: dict, data_contract: dict) -> dict:
    strategies = artifact.get("strategies", [])
    required = set(data_contract.get("strategy", {}).get("required_fields", []))
    required.update(ui_contract.get("modules", {}).get("Strategy Monitor", {}).get("required_row_fields", []))
    missing_by_field = {}
    for field in sorted(required):
        missing = []
        for strategy in strategies:
            if not _field_or_alias_present(strategy, field, STRATEGY_FIELD_ALIASES):
                missing.append(strategy.get("strategy_id", "unknown"))
        if missing:
            missing_by_field[field] = missing
    present_count = len(required) - len(missing_by_field)
    return {
        "strategy_count": len(strategies),
        "required_field_count": len(required),
        "present_for_all_count": present_count,
        "missing_by_field": missing_by_field,
        "coverage": _coverage(present_count, len(required)),
        "ui_ready_missing_fields": sorted(missing_by_field.keys()),
    }


def _audit_strategy_drilldown(artifact: dict, ui_contract: dict, data_contract: dict) -> dict:
    strategies = artifact.get("strategies", [])
    required = set(data_contract.get("strategy", {}).get("drilldown_sections", []))
    required.update(ui_contract.get("modules", {}).get("Strategy Monitor", {}).get("required_detail_sections", []))
    missing_by_section = {}
    for section in sorted(required):
        missing = []
        for strategy in strategies:
            if not _field_or_alias_present(strategy, section, DETAIL_SECTION_ALIASES):
                missing.append(strategy.get("strategy_id", "unknown"))
        if missing:
            missing_by_section[section] = missing
    present_count = len(required) - len(missing_by_section)
    return {
        "strategy_count": len(strategies),
        "required_section_count": len(required),
        "present_for_all_count": present_count,
        "missing_by_section": missing_by_section,
        "coverage": _coverage(present_count, len(required)),
    }


def _audit_allocation(artifact: dict, data_contract: dict) -> dict:
    allocation = artifact.get("allocation", {})
    required = data_contract.get("allocation", {}).get("required_fields", [])
    missing = []
    present = []
    for field in required:
        if _field_or_alias_present(allocation, field, ALLOCATION_ALIASES):
            present.append(field)
        else:
            missing.append(field)
    return {
        "required_field_count": len(required),
        "present_fields": present,
        "missing_fields": missing,
        "coverage": _coverage(len(present), len(required)),
    }


def _field_or_alias_present(payload: dict, field: str, aliases: dict[str, list[str]]) -> bool:
    if _has_path(payload, field):
        return True
    return any(_has_path(payload, path) for path in aliases.get(field, []))


def _has_path(payload: Any, path: str) -> bool:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    if current is None:
        return False
    if isinstance(current, (list, dict, str)) and not current:
        return False
    return True


def _coverage(present: int, total: int) -> float:
    return float(present / total) if total else 1.0


def _priority_gaps(report: dict) -> list[dict]:
    gaps = []
    for field in report["strategy_table"]["ui_ready_missing_fields"]:
        severity = "high" if field in {"daily_pnl", "mtd_pnl", "ytd_pnl", "rolling_sharpe", "regime_fit"} else "medium"
        gaps.append({"severity": severity, "item": f"Strategy table field: {field}", "reason": "Required for dense Strategy Monitor table."})
    for section, missing in report["strategy_drilldown"]["missing_by_section"].items():
        gaps.append({"severity": "high", "item": f"Strategy drawer section: {section}", "reason": f"Missing for {len(missing)} strategies."})
    for module in report["modules"]:
        if module["missing_data"]:
            gaps.append({"severity": "high", "item": f"Module data: {module['module']}", "reason": f"Missing {', '.join(module['missing_data'])}."})
    return gaps


def _summary(report: dict) -> dict:
    coverages = [
        _coverage(sum(1 for row in report["top_level_sections"] if row["present"]), len(report["top_level_sections"])),
        report["strategy_table"]["coverage"],
        report["strategy_drilldown"]["coverage"],
        report["allocation"]["coverage"],
    ]
    coverages.extend(module["coverage"] for module in report["modules"])
    return {
        "overall_coverage": sum(coverages) / len(coverages) if coverages else 1.0,
        "strategy_table_coverage": report["strategy_table"]["coverage"],
        "strategy_drilldown_coverage": report["strategy_drilldown"]["coverage"],
        "allocation_coverage": report["allocation"]["coverage"],
        "priority_gap_count": len(report["priority_gaps"]),
    }


def _markdown_report(report: dict) -> str:
    lines = [
        "# Dashboard Data Contract Audit",
        "",
        f"As of: {report.get('as_of_date')}",
        f"Strategy count: {report.get('strategy_count')}",
        "",
        "## Summary",
        "",
        f"- Overall coverage: {report['summary']['overall_coverage']:.1%}",
        f"- Strategy table coverage: {report['summary']['strategy_table_coverage']:.1%}",
        f"- Strategy drilldown coverage: {report['summary']['strategy_drilldown_coverage']:.1%}",
        f"- Allocation coverage: {report['summary']['allocation_coverage']:.1%}",
        f"- Priority gaps: {report['summary']['priority_gap_count']}",
        "",
        "## Priority Gaps",
        "",
    ]
    if report["priority_gaps"]:
        for gap in report["priority_gaps"]:
            lines.append(f"- **{gap['severity']}**: {gap['item']} - {gap['reason']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Module Coverage", ""])
    for module in report["modules"]:
        missing = ", ".join(module["missing_data"]) if module["missing_data"] else "none"
        lines.append(f"- {module['module']}: {module['coverage']:.1%}; missing: {missing}")
    lines.extend(["", "## Strategy Table Missing Fields", ""])
    if report["strategy_table"]["missing_by_field"]:
        for field, missing in report["strategy_table"]["missing_by_field"].items():
            lines.append(f"- {field}: missing for {len(missing)} strategies")
    else:
        lines.append("- None")
    lines.extend(["", "## Strategy Drilldown Missing Sections", ""])
    if report["strategy_drilldown"]["missing_by_section"]:
        for section, missing in report["strategy_drilldown"]["missing_by_section"].items():
            lines.append(f"- {section}: missing for {len(missing)} strategies")
    else:
        lines.append("- None")
    lines.extend(["", "## Allocation Missing Fields", ""])
    if report["allocation"]["missing_fields"]:
        for field in report["allocation"]["missing_fields"]:
            lines.append(f"- {field}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
