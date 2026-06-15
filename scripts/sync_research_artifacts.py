"""Normalize existing research artifacts into deployable canonical files.

This script copies or splits already-produced research outputs. It does not run
strategy research, backtests, or live/shadow operations.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = Path("D:/Global_Ai/risk_manager_platform")
CANONICAL_DIR = ROOT / "data/research/canonical"
MAPPING_PATH = ROOT / "data/config/strategy_research_mapping.json"
COVERAGE_PATH = ROOT / "docs/reviews/RESEARCH_ARTIFACT_COVERAGE.md"

LEGACY_FACTORY_IDS = {
    "C3A1_001",
    "C3A1_002",
    "C3A1_003",
    "C3A1_013",
    "C3A1_015",
    "C3A2_008",
}

BATCH_SOURCES = {
    "FUNDAMENTAL_MOMENTUM": "output/research/final_fundamental_research_v1",
    "EARNINGS_QUALITY": "output/research/final_fundamental_research_v1",
    "MARGIN_IMPROVEMENT": "output/research/final_fundamental_research_v1",
    "OVERNIGHT_INTRADAY_ENSEMBLE": "output/research/final_platform_delivery_v1",
    "FILING_SHOCK_CONTINUATION": "output/research/final_platform_delivery_v1",
    "FUNDAMENTAL_SHOCK_RECOVERY": "output/research/final_platform_delivery_v1",
    "CASH_FLOW_GROWTH_QUALITY": "output/research/final_platform_delivery_v1",
    "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER": "output/research/final_expanded_selection_v1",
    "LIQUIDITY_ADJUSTED_MOMENTUM": "output/research/final_ohlcv_alpha_expansion_v1",
    "POST_FILING_CASH_FLOW_SURPRISE": "output/research/event_panel_final_four_strategy_batch_v1",
}

WQ_SOURCE = (
    LEGACY_ROOT
    / "output/research/worldquant_alpha2/validation_v1/current_listed_survivorship_biased/next_open_to_close"
)


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def norm_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def cumulative(values: pd.Series) -> list[float]:
    out = []
    total = 1.0
    for value in values.fillna(0).astype(float):
        total *= 1.0 + value
        out.append(total - 1.0)
    return out


def drawdown(cumulative_returns: list[float]) -> list[float]:
    peak = 1.0
    out = []
    for value in cumulative_returns:
        equity = 1.0 + value
        peak = max(peak, equity)
        out.append(equity / peak - 1.0 if peak else 0.0)
    return out


def normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.sort_values("date").copy()
    for column in ["gross_return", "transaction_cost", "net_return", "turnover"]:
        if column not in daily.columns:
            daily[column] = 0.0
    if "cumulative_gross" not in daily.columns:
        if "gross_cumulative_value" in daily.columns:
            daily["cumulative_gross"] = daily["gross_cumulative_value"].astype(float) - 1.0
        else:
            daily["cumulative_gross"] = cumulative(daily["gross_return"])
    if "cumulative_net" not in daily.columns:
        if "net_cumulative_value" in daily.columns:
            daily["cumulative_net"] = daily["net_cumulative_value"].astype(float) - 1.0
        else:
            daily["cumulative_net"] = cumulative(daily["net_return"])
    if "drawdown" not in daily.columns:
        daily["drawdown"] = drawdown(daily["cumulative_net"].astype(float).tolist())
    return daily[
        ["date", "gross_return", "transaction_cost", "net_return", "turnover", "cumulative_gross", "cumulative_net", "drawdown"]
    ]


def normalized_summary(strategy_id: str, source: str, row: dict[str, Any], daily: pd.DataFrame) -> dict[str, Any]:
    net = daily["net_return"].astype(float)
    gross = daily["gross_return"].astype(float)
    cumulative_net = norm_float(row.get("cumulative_net_return") or row.get("net_cumulative_return"))
    cumulative_gross = norm_float(row.get("cumulative_gross_return") or row.get("gross_cumulative_return"))
    if cumulative_net is None:
        cumulative_net = float(daily["cumulative_net"].iloc[-1])
    if cumulative_gross is None:
        cumulative_gross = float(daily["cumulative_gross"].iloc[-1])
    total_cost = norm_float(row.get("transaction_cost_sum") or row.get("total_cost_drag"))
    if total_cost is None:
        total_cost = float(daily["transaction_cost"].sum())
    return {
        "strategy_id": strategy_id,
        "source_provenance": source,
        "research_commit": row.get("code_commit") or row.get("research_commit") or "LEGACY_SOURCE_COMMIT_NOT_RECORDED",
        "sample_start": str(daily["date"].iloc[0]),
        "sample_end": str(daily["date"].iloc[-1]),
        "observations": int(len(daily)),
        "cumulative_gross_return": cumulative_gross,
        "cumulative_net_return": cumulative_net,
        "gross_cumulative_return": cumulative_gross,
        "net_cumulative_return": cumulative_net,
        "annualized_return": norm_float(row.get("annualized_net_return")),
        "net_sharpe": norm_float(row.get("net_sharpe")),
        "annualized_net_volatility": norm_float(row.get("annualized_net_volatility") or row.get("annualized_volatility")),
        "max_drawdown": norm_float(row.get("max_drawdown") or row.get("maximum_drawdown")),
        "average_daily_turnover": norm_float(row.get("average_daily_turnover")),
        "transaction_cost_sum": total_cost,
        "cost_drag_ratio": total_cost / abs(cumulative_gross) if cumulative_gross else None,
        "win_rate": float((net > 0).sum() / len(net)) if len(net) else None,
        "gross_return_mean": float(gross.mean()) if len(gross) else None,
        "net_return_mean": float(net.mean()) if len(net) else None,
        "preliminary_oos_net_return": norm_float(row.get("preliminary_oos_net_return")),
        "preliminary_oos_sharpe": norm_float(row.get("preliminary_oos_sharpe")),
        "double_cost_net_return": norm_float(row.get("double_cost_net_return")),
        "delayed_execution_net_return": norm_float(row.get("delayed_execution_net_return")),
        "maximum_active_correlation": norm_float(row.get("maximum_active_correlation")),
        "marginal_combined_portfolio_sharpe": norm_float(row.get("marginal_combined_portfolio_sharpe")),
        "decision": row.get("recommendation") or row.get("classification") or row.get("status_recommendation"),
        "research_status": row.get("research_status") or row.get("run_status"),
        "labels": row.get("labels"),
        "raw_summary_row": row,
    }


def write_strategy_artifact(
    strategy_id: str,
    display_id: str,
    strategy_name: str,
    source_dir: Path,
    summary_row: dict[str, Any],
    daily: pd.DataFrame,
    *,
    mapping_status: str = "CONNECTED",
    blocker: str,
) -> dict[str, Any]:
    target = CANONICAL_DIR / strategy_id
    target.mkdir(parents=True, exist_ok=True)
    normalized_daily = normalize_daily(daily)
    normalized_daily.to_csv(target / "daily_returns.csv", index=False)
    summary = normalized_summary(strategy_id, str(source_dir), summary_row, normalized_daily)
    write_json(target / "summary.json", summary)
    write_json(
        target / "provenance.json",
        {
            "strategy_id": strategy_id,
            "source_provenance": str(source_dir),
            "canonical_summary": repo_rel(target / "summary.json"),
            "canonical_return_series": repo_rel(target / "daily_returns.csv"),
            "operation": "copied_or_split_existing_research_output",
            "backtest_rerun": False,
        },
    )
    return {
        "display_id": display_id,
        "strategy_name": strategy_name,
        "registry_entry": None,
        "research_summary_artifact": repo_rel(target / "summary.json"),
        "research_return_series_artifact": repo_rel(target / "daily_returns.csv"),
        "validation_artifact": repo_rel(target / "provenance.json"),
        "holdout_artifact": None,
        "oos_artifact": None,
        "stress_test_artifact": None,
        "research_commit": summary["research_commit"],
        "source_provenance": str(source_dir),
        "mapping_status": mapping_status,
        "blocker": blocker,
    }


def migrate_factory(strategy: dict[str, Any]) -> dict[str, Any]:
    strategy_id = strategy["internal_id"]
    source_dir = LEGACY_ROOT / f"output/research/strategy_factory_v1/{strategy_id}"
    summary = read_json(source_dir / "summary.json", {})
    daily = pd.read_csv(source_dir / "daily_returns.csv")
    return write_strategy_artifact(
        strategy_id,
        strategy["display_id"],
        strategy["name"],
        source_dir,
        summary | {"code_commit": summary.get("research_commit")},
        daily,
        blocker="Validation, holdout, OOS, and stress-test artifacts were not generated in the migrated Strategy Factory baseline.",
    )


def migrate_batch(strategy: dict[str, Any]) -> dict[str, Any]:
    strategy_id = strategy["internal_id"]
    source_dir = ROOT / BATCH_SOURCES[strategy_id]
    summary_df = pd.read_csv(source_dir / "candidate_summary.csv")
    summary_row = summary_df[summary_df["strategy_id"].astype(str) == strategy_id].iloc[0].to_dict()
    daily_name = "daily_net_returns.csv" if (source_dir / "daily_net_returns.csv").exists() else "daily_strategy_returns.csv"
    daily_df = pd.read_csv(source_dir / daily_name)
    daily = daily_df[daily_df["strategy_id"].astype(str) == strategy_id].copy()
    return write_strategy_artifact(
        strategy_id,
        strategy["display_id"],
        strategy["name"],
        source_dir,
        summary_row,
        daily,
        blocker="Research artifact is connected; labels remain research-only and are not operational execution evidence.",
    )


def migrate_wq(strategy: dict[str, Any]) -> dict[str, Any]:
    summary_df = pd.read_csv(WQ_SOURCE / "validation_summary.csv")
    row = summary_df.iloc[0].to_dict()
    row["strategy_id"] = "WQ_ALPHA_018"
    daily = pd.read_csv(WQ_SOURCE / "daily_strategy_returns.csv")
    return write_strategy_artifact(
        "WQ_ALPHA_018",
        strategy["display_id"],
        strategy["name"],
        WQ_SOURCE,
        row,
        daily,
        mapping_status="CONNECTED_RESEARCH_ONLY",
        blocker="Historical research validation is connected, but WQ remains Approved Pending until canonical paper execution, price, trade, and position evidence exists.",
    )


def build_combined(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    members = [
        row["internal_id"]
        for row in strategies
        if row["membership_state"] == "executed" and row["internal_id"] != "COMBINED_PORTFOLIO"
    ]
    frames = []
    for strategy_id in members:
        path = CANONICAL_DIR / strategy_id / "daily_returns.csv"
        if path.exists():
            df = pd.read_csv(path, usecols=["date", "gross_return", "transaction_cost", "net_return", "turnover"])
            df = df.rename(
                columns={
                    "gross_return": f"{strategy_id}__gross_return",
                    "transaction_cost": f"{strategy_id}__transaction_cost",
                    "net_return": f"{strategy_id}__net_return",
                    "turnover": f"{strategy_id}__turnover",
                }
            )
            frames.append(df)
    if len(frames) < 2:
        raise RuntimeError("insufficient member research series for Combined Portfolio")
    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.merge(frame, on="date", how="inner")
    daily = pd.DataFrame({"date": combined["date"]})
    for column in ["gross_return", "transaction_cost", "net_return", "turnover"]:
        member_columns = [c for c in combined.columns if c.endswith(f"__{column}")]
        daily[column] = combined[member_columns].mean(axis=1)
    entry = write_strategy_artifact(
        "COMBINED_PORTFOLIO",
        "#COMBINED",
        "Combined",
        CANONICAL_DIR / "COMBINED_PORTFOLIO/member_equal_weight_research_composite",
        {
            "strategy_id": "COMBINED_PORTFOLIO",
            "code_commit": "LOCAL_RESEARCH_ARTIFACT_COMPOSITE",
            "recommendation": "RESEARCH_COMPOSITE_CONSTRUCTED",
        },
        daily,
        mapping_status="CONNECTED_COMPOSITE",
        blocker="Equal-weight research composite constructed from aligned canonical ordinary strategy research series; not an operational ledger.",
    )
    provenance = read_json(CANONICAL_DIR / "COMBINED_PORTFOLIO/provenance.json", {})
    provenance["member_internal_ids"] = members
    provenance["aligned_observations"] = int(len(daily))
    write_json(CANONICAL_DIR / "COMBINED_PORTFOLIO/provenance.json", provenance)
    return entry


def coverage_markdown(strategies: list[dict[str, Any]], entries: dict[str, Any]) -> str:
    lines = [
        "# Research Artifact Coverage",
        "",
        "Generated from existing local and legacy research artifacts. No backtests were rerun.",
        "",
        "| Strategy | Display | Mapping Status | Summary | Return Series | Source | Limitation |",
        "|---|---:|---|---|---|---|---|",
    ]
    for strategy in strategies:
        strategy_id = strategy["internal_id"]
        entry = entries.get(strategy_id, {})
        lines.append(
            "| {sid} | {display} | {status} | {summary} | {series} | {source} | {blocker} |".format(
                sid=strategy_id,
                display=strategy.get("display_id", ""),
                status=entry.get("mapping_status", "ARTIFACT_GENUINELY_MISSING"),
                summary=entry.get("research_summary_artifact") or "N/A",
                series=entry.get("research_return_series_artifact") or "N/A",
                source=str(entry.get("source_provenance") or "N/A").replace("|", "/"),
                blocker=str(entry.get("blocker") or "").replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    canonical = read_json(ROOT / "dashboard/data/canonical_operational.json", {})
    strategies = canonical["strategies"]
    entries: dict[str, Any] = {}
    for strategy in strategies:
        strategy_id = strategy["internal_id"]
        if strategy_id == "COMBINED_PORTFOLIO":
            continue
        if strategy_id in LEGACY_FACTORY_IDS:
            entries[strategy_id] = migrate_factory(strategy)
        elif strategy_id in BATCH_SOURCES:
            entries[strategy_id] = migrate_batch(strategy)
        elif strategy_id == "WQ_ALPHA_018":
            entries[strategy_id] = migrate_wq(strategy)
        else:
            entries[strategy_id] = {
                "display_id": strategy.get("display_id"),
                "strategy_name": strategy.get("name"),
                "research_summary_artifact": None,
                "research_return_series_artifact": None,
                "mapping_status": "ARTIFACT_GENUINELY_MISSING",
                "blocker": "No exact strategy_id match found in current or legacy research outputs.",
            }
    entries["COMBINED_PORTFOLIO"] = build_combined(strategies)
    ordered_entries = {
        strategy["internal_id"]: entries[strategy["internal_id"]]
        for strategy in strategies
        if strategy["internal_id"] in entries
    }
    write_json(
        MAPPING_PATH,
        {
            "version": "2.0.0",
            "entries": ordered_entries,
            "default_status": "ARTIFACT_GENUINELY_MISSING",
            "default_blocker": "No exact deployable canonical summary/return-series mapping is available for this strategy.",
        },
    )
    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_PATH.write_text(coverage_markdown(strategies, ordered_entries), encoding="utf-8")
    print(f"wrote {len(ordered_entries)} research mappings")


if __name__ == "__main__":
    main()
