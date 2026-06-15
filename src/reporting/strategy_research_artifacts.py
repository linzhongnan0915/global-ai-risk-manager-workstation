"""Load deployable, repository-relative historical research evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import pandas as pd


def _rolling_sharpe(values: list[float], window: int = 63) -> list[float | None]:
    result: list[float | None] = []
    for end in range(1, len(values) + 1):
        sample = values[max(0, end - window):end]
        if len(sample) < window or pstdev(sample) == 0:
            result.append(None)
        else:
            result.append(mean(sample) / pstdev(sample) * math.sqrt(252))
    return result


def load_strategy_research_artifacts(root: Path, strategies: list[dict[str, Any]]) -> dict[str, Any]:
    """Return evidence for every strategy without depending on the legacy project."""
    mapping_path = root / "data/config/strategy_research_mapping.json"
    if not mapping_path.exists():
        return {}
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    entries = mapping["entries"]
    evidence: dict[str, Any] = {}
    for strategy in strategies:
        strategy_id = strategy["internal_id"]
        entry = entries.get(strategy_id)
        if not entry:
            evidence[strategy_id] = {
                "research_status": mapping["default_status"],
                "mapping_status": mapping["default_status"],
                "limitations": mapping["default_blocker"],
                "exact_blocker": mapping["default_blocker"],
                "research_metrics": {},
                "research_series": {},
                "evidence_artifact": None,
                "research_source_commit": None,
            }
            continue
        summary_path = root / entry["research_summary_artifact"]
        series_path = root / entry["research_return_series_artifact"]
        if not summary_path.exists() or not series_path.exists():
            blocker = f"ARTIFACT_SCHEMA_INCOMPATIBLE: missing deployable artifact {entry['research_summary_artifact'] if not summary_path.exists() else entry['research_return_series_artifact']}"
            evidence[strategy_id] = {
                "research_status": "ARTIFACT_SCHEMA_INCOMPATIBLE",
                "mapping_status": "ARTIFACT_SCHEMA_INCOMPATIBLE",
                "limitations": blocker,
                "exact_blocker": blocker,
                "research_metrics": {},
                "research_series": {},
                "evidence_artifact": entry["research_summary_artifact"],
                "research_source_commit": entry["research_commit"],
            }
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        daily = pd.read_csv(series_path).sort_values("date")
        net = daily["net_return"].astype(float).tolist()
        annualized_return = (1 + float(summary["cumulative_net_return"])) ** (252 / len(net)) - 1
        evidence[strategy_id] = {
            "research_status": "CONNECTED",
            "mapping_status": entry["mapping_status"],
            "limitations": entry["blocker"],
            "exact_blocker": entry["blocker"],
            "research_source_commit": entry["research_commit"],
            "evidence_artifact": entry["research_summary_artifact"],
            "research_metrics": {
                "annualized_return": annualized_return,
                "net_sharpe": summary.get("net_sharpe"),
                "annualized_volatility": summary.get("annualized_net_volatility"),
                "max_drawdown": summary.get("max_drawdown"),
                "win_rate": sum(value > 0 for value in net) / len(net),
                "average_daily_turnover": summary.get("average_daily_turnover"),
                "cost_drag": summary.get("transaction_cost_sum"),
                "cost_drag_ratio": summary.get("cost_drag_ratio"),
                "observation_count": len(net),
                "sample_start": str(daily.iloc[0]["date"]),
                "sample_end": str(daily.iloc[-1]["date"]),
                "research_decision": summary.get("decision"),
                "rolling_63d_sharpe_latest": next((value for value in reversed(_rolling_sharpe(net)) if value is not None), None),
            },
            "research_series": {
                "dates": daily["date"].astype(str).tolist(),
                "gross_equity": daily["cumulative_gross"].astype(float).tolist(),
                "net_equity": daily["cumulative_net"].astype(float).tolist(),
                "drawdown": daily["drawdown"].astype(float).tolist(),
                "rolling_63d_sharpe": _rolling_sharpe(net),
                "return_distribution": net,
            },
        }
    return evidence
