"""Build the rapid 20+1 research artifacts, correlation matrix, and Strategy 21 composite."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
import json

import pandas as pd

from src.risk.performance import cumulative_returns, drawdown_series, max_drawdown, sharpe_ratio, volatility
from src.strategies.composite_membership import (
    composite_membership_for,
    composite_weights,
    eligible_composite_constituent_ids,
    equal_composite_weight,
    passes_composite_gate,
)
from src.strategies.platform_registry import (
    COMPOSITE_ID,
    COMPOSITE_LABEL,
    COMPOSITE_NAME,
    RAPID_BACKTEST_IDS,
    SPEC_BY_ID,
)
from src.strategies.literature_backtests import _annual_return


def ensure_spy_benchmark(dates: pd.DatetimeIndex, cache_path: Path) -> pd.Series:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        frame = pd.read_csv(cache_path, parse_dates=["date"])
        return frame.set_index("date")["return"].sort_index()
    import yfinance as yf

    start = (dates.min() - pd.Timedelta(days=5)).date().isoformat()
    end = (dates.max() + pd.Timedelta(days=5)).date().isoformat()
    history = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)
    if history.empty:
        raise RuntimeError("Failed to download SPY benchmark via yfinance.")
    close = history["Close"] if "Close" in history.columns else history.iloc[:, 0]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    returns = close.pct_change().rename("return")
    returns.index = pd.to_datetime(returns.index)
    if getattr(returns.index, "tz", None) is not None:
        returns.index = returns.index.tz_localize(None)
    pd.DataFrame({"date": returns.index, "return": returns.to_numpy()}).to_csv(cache_path, index=False)
    return returns.reindex(dates).fillna(0.0)


def load_daily_returns(factory_root: Path, strategy_ids: tuple[str, ...]) -> pd.DataFrame:
    return load_aligned_return_panels(factory_root, strategy_ids)[1]


def load_aligned_return_panels(
    factory_root: Path, strategy_ids: tuple[str, ...]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    gross_frames = []
    net_frames = []
    for strategy_id in strategy_ids:
        path = factory_root / strategy_id / "daily_returns.csv"
        daily = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        gross_frames.append(daily["gross_return"].rename(strategy_id))
        net_frames.append(daily["net_return"].rename(strategy_id))
    gross = pd.concat(gross_frames, axis=1, join="inner")
    net = pd.concat(net_frames, axis=1, join="inner")
    valid = gross.notna().all(axis=1) & net.notna().all(axis=1)
    return gross.loc[valid], net.loc[valid]


def resolve_composite_active_ids(
    factory_root: Path, returns_all: pd.DataFrame
) -> tuple[tuple[str, ...], list[dict[str, object]]]:
    """Derive composite members dynamically from the canonical registry gate (1/N equal weight)."""
    del returns_all  # membership does not depend on correlation backfill slots
    active = eligible_composite_constituent_ids(factory_root)
    return active, []


def classify_research_status(
    summary: dict[str, object],
    max_abs_corr: float | None,
) -> str:
    if not summary.get("run_valid", False):
        return "FAIL"
    if float(summary.get("net_sharpe") or 0) <= 0:
        return "WATCH"
    if max_abs_corr is not None and max_abs_corr > 0.75:
        return "WATCH"
    return "PASS"


def composite_membership(strategy_id: str, status: str, summary: dict[str, object], composite_active_ids: set[str]) -> str:
    del status, summary
    return composite_membership_for(strategy_id, composite_active_ids)


def correlation_diagnostics(returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, object]]]:
    corr = returns.corr()
    rows = []
    pair_rows = []
    for strategy_id in returns.columns:
        others = corr[strategy_id].drop(strategy_id).abs()
        rows.append(
            {
                "strategy_id": strategy_id,
                "average_abs_correlation": float(others.mean()) if len(others) else 0.0,
                "max_abs_correlation": float(others.max()) if len(others) else 0.0,
                "highest_corr_partner": others.idxmax() if len(others) else "",
            }
        )
    for left, right in combinations(returns.columns, 2):
        pair_rows.append({"strategy_left": left, "strategy_right": right, "correlation": float(corr.loc[left, right])})
    return corr, pd.DataFrame(rows), pair_rows


def build_equal_weight_composite(
    gross_returns: pd.DataFrame, net_returns: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, object]]:
    n = len(net_returns.columns)
    weight = equal_composite_weight(n)
    weights = composite_weights(tuple(net_returns.columns))
    gross_composite = gross_returns.mul(weight).sum(axis=1)
    net_composite = net_returns.mul(weight).sum(axis=1)
    cost = gross_composite - net_composite
    daily = pd.DataFrame(
        {
            "date": net_returns.index,
            "gross_return": gross_composite,
            "net_return": net_composite,
            "transaction_cost": cost,
            "turnover": pd.Series(0.0, index=net_returns.index),
        }
    )
    daily["cumulative_gross"] = cumulative_returns(daily["gross_return"])
    daily["cumulative_net"] = cumulative_returns(daily["net_return"])
    daily["drawdown"] = drawdown_series(daily["net_return"])
    gross_total = float(daily["gross_return"].sum())
    cost_total = float(daily["transaction_cost"].sum())
    summary = {
        "strategy_id": COMPOSITE_ID,
        "name": COMPOSITE_NAME,
        "label": COMPOSITE_LABEL.replace("eligible ACTIVE underlying strategies", f"{n} eligible ACTIVE underlying strategies"),
        "research_only": True,
        "not_allocation_approved": True,
        "N": n,
        "equal_weight": weight,
        "weight_formula": "weight_i = 1 / N",
        "dynamic_membership": True,
        "eligible_member_ids": list(net_returns.columns),
        "constituent_ids": list(net_returns.columns),
        "constituent_weights": weights,
        "constituent_sharpes": {col: float(sharpe_ratio(net_returns[col])) for col in net_returns.columns},
        "common_start_date": net_returns.index.min().date().isoformat(),
        "common_end_date": net_returns.index.max().date().isoformat(),
        "observations": int(len(net_returns)),
        "cumulative_gross_return": float(daily["cumulative_gross"].iloc[-1]),
        "cumulative_net_return": float(daily["cumulative_net"].iloc[-1]),
        "annualized_return": _annual_return(net_composite),
        "annualized_gross_return": _annual_return(gross_composite),
        "annualized_volatility": float(volatility(net_composite)),
        "sharpe": float(sharpe_ratio(net_composite)),
        "max_drawdown": float(max_drawdown(net_composite)),
        "cost_drag": float(cost_total / gross_total) if gross_total > 0 else None,
        "composite_cost_total": cost_total,
        "weight_formula": "weight_i = 1 / N",
    }
    return daily, summary


def export_current_holdings(factory_root: Path, strategy_ids: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for strategy_id in strategy_ids:
        audit_path = factory_root / strategy_id / "rebalance_audit.csv"
        if not audit_path.exists():
            continue
        audit = pd.read_csv(audit_path, parse_dates=["date"])
        if audit.empty:
            continue
        last_date = audit["date"].max()
        latest = audit.loc[audit["date"] == last_date]
        latest = latest.loc[latest["target_weight"] != 0].sort_values("rank", ascending=False)
        for _, row in latest.iterrows():
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "side": "long" if row["target_weight"] > 0 else "short",
                    "ticker": row["ticker"],
                    "weight": float(row["target_weight"]),
                    "signal_rank": float(row["rank"]),
                    "last_rebalance_date": last_date.date().isoformat(),
                }
            )
    return pd.DataFrame(rows)


def build_leaderboard(
    factory_root: Path,
    strategy_ids: tuple[str, ...],
    corr_metrics: pd.DataFrame,
    composite_active_ids: set[str],
) -> pd.DataFrame:
    corr_lookup = corr_metrics.set_index("strategy_id")
    rows = []
    for strategy_id in strategy_ids:
        summary = json.loads((factory_root / strategy_id / "summary.json").read_text(encoding="utf-8"))
        spec = SPEC_BY_ID[strategy_id]
        metrics = corr_lookup.loc[strategy_id] if strategy_id in corr_lookup.index else {}
        status = classify_research_status(summary, metrics.get("max_abs_correlation"))
        membership = composite_membership(strategy_id, status, summary, composite_active_ids)
        net = pd.read_csv(factory_root / strategy_id / "daily_returns.csv", parse_dates=["date"]).set_index("date")["net_return"]
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": spec.name,
                "status": status,
                "membership": membership,
                "net_return": float(summary.get("cumulative_net_return") or 0),
                "annualized_return": _annual_return(net),
                "sharpe": float(summary.get("net_sharpe") or 0),
                "volatility": float(summary.get("annualized_net_volatility") or 0),
                "max_drawdown": float(summary.get("max_drawdown") or 0),
                "average_turnover": float(summary.get("average_daily_turnover") or 0),
                "cost_drag": float(summary.get("cost_drag_ratio") or 0),
                "average_abs_correlation": metrics.get("average_abs_correlation"),
                "max_abs_correlation": metrics.get("max_abs_correlation"),
                "highest_corr_partner": metrics.get("highest_corr_partner"),
            }
        )
    return pd.DataFrame(rows)


def write_summary_markdown(path: Path, leaderboard: pd.DataFrame, composite_summary: dict[str, object], pair_rows: list[dict[str, object]]) -> None:
    status_counts = leaderboard["status"].value_counts().to_dict()
    membership_counts = leaderboard["membership"].value_counts().to_dict()
    active_count = int(membership_counts.get("ACTIVE", 0))
    reference_count = int(membership_counts.get("REFERENCE_ONLY", 0))
    top5 = leaderboard.sort_values("sharpe", ascending=False).head(5)
    bottom5 = leaderboard.sort_values("sharpe", ascending=True).head(5)
    highest = max(pair_rows, key=lambda row: abs(row["correlation"]))
    lowest = min(pair_rows, key=lambda row: abs(row["correlation"]))
    high_overlap = sum(1 for row in pair_rows if abs(row["correlation"]) > 0.75)
    lines = [
        "# Combined Portfolio Research Summary",
        "",
        f"- Combined Portfolio includes all currently eligible ACTIVE strategies",
        f"- Total backtested underlying strategies: {len(RAPID_BACKTEST_IDS)}",
        f"- ACTIVE Combined Portfolio members: {active_count}",
        f"- REFERENCE ONLY (excluded from Combined Portfolio): {reference_count}",
        f"- PASS: {status_counts.get('PASS', 0)}",
        f"- WATCH: {status_counts.get('WATCH', 0)}",
        f"- FAIL: {status_counts.get('FAIL', 0)}",
        "",
        "## Combined Portfolio",
        f"- Sharpe: {composite_summary['sharpe']:.3f}",
        f"- Annualized return: {composite_summary['annualized_return']:.2%}",
        f"- Max drawdown: {composite_summary['max_drawdown']:.2%}",
        f"- Weight formula: {composite_summary['weight_formula']} (N={composite_summary['N']}, weight={composite_summary['equal_weight']:.2%})",
        "",
        "## Correlation",
        f"- Highest pair: {highest['strategy_left']} / {highest['strategy_right']} = {highest['correlation']:.3f}",
        f"- Lowest pair: {lowest['strategy_left']} / {lowest['strategy_right']} = {lowest['correlation']:.3f}",
        f"- Pairs above 0.75 abs correlation: {high_overlap}",
        "",
        "## Top 5 Sharpe",
    ]
    for _, row in top5.iterrows():
        lines.append(f"- {row['strategy_id']} ({row['strategy_name']}): {row['sharpe']:.3f}")
    lines.extend(["", "## Bottom 5 Sharpe"])
    for _, row in bottom5.iterrows():
        lines.append(f"- {row['strategy_id']} ({row['strategy_name']}): {row['sharpe']:.3f}")
    lines.extend(["", "## Limitations", "- yfinance OHLCV only; Pilot 500 survivorship-biased universe.", "- Research-only; not live allocation approved.", "- No walk-forward optimization or parameter search."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_combined_portfolio_charts(composite_daily: pd.DataFrame, active_corr: pd.DataFrame, artifact_root: Path, composite_root: Path) -> dict[str, str]:
    import matplotlib.pyplot as plt

    paths: dict[str, str] = {}
    chart_daily = composite_daily.copy()
    chart_daily["date"] = pd.to_datetime(chart_daily["date"])
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(chart_daily["date"], chart_daily["cumulative_net"], label="Combined Portfolio (net)")
    axes[0].set_title("Combined Portfolio Equity Curve")
    axes[0].set_ylabel("Cumulative return")
    axes[0].legend()
    axes[0].grid(alpha=0.3)
    axes[1].plot(chart_daily["date"], chart_daily["drawdown"], color="firebrick", label="Drawdown")
    axes[1].set_title("Combined Portfolio Drawdown")
    axes[1].set_ylabel("Drawdown")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    plt.tight_layout()
    for target in (artifact_root / "combined_portfolio_equity_drawdown.png", composite_root / "combined_portfolio_equity_drawdown.png"):
        plt.savefig(target, dpi=140)
        paths[target.name] = str(target)
    plt.close()

    if not active_corr.empty:
        fig, ax = plt.subplots(figsize=(11, 9))
        im = ax.imshow(active_corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(active_corr.columns)), active_corr.columns, rotation=90, fontsize=7)
        ax.set_yticks(range(len(active_corr.index)), active_corr.index, fontsize=7)
        ax.set_title("Combined Portfolio Member Correlation Matrix")
        fig.colorbar(im, ax=ax, fraction=0.046)
        plt.tight_layout()
        for target in (artifact_root / "combined_portfolio_correlation_heatmap.png", composite_root / "combined_portfolio_correlation_heatmap.png"):
            plt.savefig(target, dpi=140)
            paths[target.name] = str(target)
        plt.close()
    return paths


def write_evidence_manifest(
    artifact_root: Path,
    composite_root: Path,
    leaderboard: pd.DataFrame,
    composite_summary: dict[str, object],
    chart_paths: dict[str, str],
) -> Path:
    active = leaderboard.loc[leaderboard["membership"] == "ACTIVE"]
    reference = leaderboard.loc[leaderboard["membership"] == "REFERENCE_ONLY"]
    per_strategy = []
    factory_root = artifact_root.parents[1] / "output/research/strategy_factory_v1"
    for _, row in leaderboard.iterrows():
        strategy_id = row["strategy_id"]
        strategy_dir = factory_root / strategy_id
        per_strategy.append(
            {
                "strategy_id": strategy_id,
                "membership": row["membership"],
                "status": row["status"],
                "sharpe": float(row["sharpe"]),
                "net_return": float(row["net_return"]),
                "max_drawdown": float(row["max_drawdown"]),
                "average_turnover": float(row["average_turnover"]),
                "artifacts": {
                    name: str(strategy_dir / name)
                    for name in (
                        "summary.json",
                        "daily_returns.csv",
                        "equity_curve.png",
                        "drawdown.png",
                        "decile_chart.png",
                        "screening_report.md",
                        "ic_decile_summary.csv",
                    )
                    if (strategy_dir / name).exists()
                },
            }
        )
    manifest = {
        "composite_id": COMPOSITE_ID,
        "composite_name": COMPOSITE_NAME,
        "dynamic_membership": True,
        "active_member_count": int(len(active)),
        "reference_only_count": int(len(reference)),
        "weight_formula": composite_summary.get("weight_formula"),
        "equal_weight": composite_summary.get("equal_weight"),
        "composite_metrics": {
            "sharpe": composite_summary.get("sharpe"),
            "annualized_return": composite_summary.get("annualized_return"),
            "max_drawdown": composite_summary.get("max_drawdown"),
            "cumulative_net_return": composite_summary.get("cumulative_net_return"),
            "observations": composite_summary.get("observations"),
        },
        "governance_limits": {
            "composite_entry_requires": [
                "run_valid",
                "cumulative_net_return > 0",
                "net_sharpe > 0",
                "selected into composite active set",
            ],
            "reference_only_if": ["net_sharpe <= 0", "run_valid == false", "fails composite eligibility gate"],
            "allocation_approved": False,
            "research_only": True,
            "data_source": "yfinance OHLCV Pilot 500",
            "survivorship_bias": True,
        },
        "charts": chart_paths,
        "artifacts": {
            "leaderboard_csv": str(artifact_root / "strategy_leaderboard.csv"),
            "correlation_matrix_csv": str(artifact_root / "correlation_matrix.csv"),
            "correlation_matrix_all_tested_csv": str(artifact_root / "correlation_matrix_all_tested.csv"),
            "combined_portfolio_summary_json": str(artifact_root / "combined_portfolio_summary.json"),
            "combined_portfolio_daily_returns_csv": str(artifact_root / "combined_portfolio_daily_returns.csv"),
            "current_holdings_csv": str(artifact_root / "current_holdings.csv"),
            "summary_markdown": str(artifact_root / "combined_portfolio_report.md"),
        },
        "members": per_strategy,
    }
    path = artifact_root / "combined_portfolio_evidence_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (composite_root / "combined_portfolio_evidence_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def write_combined_portfolio_report(
    path: Path,
    leaderboard: pd.DataFrame,
    composite_summary: dict[str, object],
    pair_rows: list[dict[str, object]],
    chart_paths: dict[str, str],
) -> None:
    active = leaderboard.loc[leaderboard["membership"] == "ACTIVE"]
    reference = leaderboard.loc[leaderboard["membership"] == "REFERENCE_ONLY"]
    highest = max(pair_rows, key=lambda row: abs(row["correlation"]))
    lowest = min(pair_rows, key=lambda row: abs(row["correlation"]))
    lines = [
        "# Combined Portfolio Research Report",
        "",
        "## Summary",
        f"- Composite: **{COMPOSITE_NAME}** (`{COMPOSITE_ID}`)",
        f"- Combined Portfolio includes all currently eligible ACTIVE strategies",
        f"- Active members in composite: {len(active)}",
        f"- Reference-only (excluded): {len(reference)}",
        f"- Weight formula: {composite_summary['weight_formula']} (N={composite_summary['N']}, weight={composite_summary['equal_weight']:.2%})",
        "",
        "## Combined Portfolio Performance",
        f"- Sharpe: {composite_summary['sharpe']:.3f}",
        f"- Annualized return: {composite_summary['annualized_return']:.2%}",
        f"- Cumulative gross return: {composite_summary.get('cumulative_gross_return', 0):.2%}",
        f"- Cumulative net return: {composite_summary['cumulative_net_return']:.2%}",
        f"- Composite cost drag: {composite_summary.get('cost_drag', 0):.2%}",
        f"- Max drawdown: {composite_summary['max_drawdown']:.2%}",
        f"- Observations: {composite_summary['observations']}",
        "",
        "## Governance / Limits",
        "- Entry gate: run_valid AND cumulative net return > 0 AND net Sharpe > 0.",
        "- Negative-Sharpe or failed runs are reference-only with zero composite weight.",
        "- Research-only; not allocation approved; no walk-forward optimization.",
        "- yfinance OHLCV on Pilot 500; survivorship-biased current-listed universe.",
        "",
        "## Evidence Artifacts",
        f"- Equity/drawdown chart: `{chart_paths.get('combined_portfolio_equity_drawdown.png', 'missing')}`",
        f"- Correlation heatmap: `{chart_paths.get('combined_portfolio_correlation_heatmap.png', 'missing')}`",
        "- Manifest: `artifacts/rapid_20plus1/combined_portfolio_evidence_manifest.json`",
        "- Leaderboard: `artifacts/rapid_20plus1/strategy_leaderboard.csv`",
        "",
        "## Correlation Diagnostics",
        f"- Highest pair: {highest['strategy_left']} / {highest['strategy_right']} = {highest['correlation']:.3f}",
        f"- Lowest pair: {lowest['strategy_left']} / {lowest['strategy_right']} = {lowest['correlation']:.3f}",
        "",
        "## Active Members",
    ]
    for _, row in active.sort_values("sharpe", ascending=False).iterrows():
        lines.append(f"- {row['strategy_id']} ({row['strategy_name']}): Sharpe {row['sharpe']:.3f}, net {row['net_return']:.2%}")
    if not reference.empty:
        lines.extend(["", "## Reference Only"])
        for _, row in reference.sort_values("sharpe", ascending=False).iterrows():
            lines.append(f"- {row['strategy_id']} ({row['strategy_name']}): Sharpe {row['sharpe']:.3f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize_rapid_artifacts(project_root: Path) -> dict[str, object]:
    root = Path(project_root)
    factory_root = root / "output/research/strategy_factory_v1"
    composite_root = root / "output/research/strategy_21_research_composite_v1"
    artifact_root = root / "artifacts/rapid_20plus1"
    artifact_root.mkdir(parents=True, exist_ok=True)
    composite_root.mkdir(parents=True, exist_ok=True)

    returns_all = load_daily_returns(factory_root, RAPID_BACKTEST_IDS)
    active_ids, replacement_notes = resolve_composite_active_ids(factory_root, returns_all)
    composite_active_ids = set(active_ids)
    corr, corr_metrics, _ = correlation_diagnostics(returns_all)
    leaderboard = build_leaderboard(factory_root, RAPID_BACKTEST_IDS, corr_metrics, composite_active_ids)
    leaderboard.to_csv(artifact_root / "strategy_leaderboard.csv", index=False)

    reference_ids = tuple(leaderboard.loc[leaderboard["membership"] == "REFERENCE_ONLY", "strategy_id"].tolist())
    gross_all, net_all = load_aligned_return_panels(factory_root, RAPID_BACKTEST_IDS)
    active_gross = gross_all[list(active_ids)] if len(active_ids) else gross_all.iloc[:, :0]
    active_net = net_all[list(active_ids)] if len(active_ids) else net_all.iloc[:, :0]
    active_corr = active_net.corr() if len(active_ids) >= 2 else pd.DataFrame()
    _, _, active_pair_rows = correlation_diagnostics(active_net) if len(active_ids) >= 2 else (pd.DataFrame(), pd.DataFrame(), [])
    if not active_corr.empty:
        active_corr.to_csv(artifact_root / "correlation_matrix.csv")
    corr.to_csv(artifact_root / "correlation_matrix_all_tested.csv")

    composite_daily, composite_summary = build_equal_weight_composite(active_gross, active_net)
    composite_summary["active_member_ids"] = list(active_ids)
    composite_summary["reference_only_ids"] = list(reference_ids)
    composite_summary["replacement_notes"] = replacement_notes
    composite_summary["tested_underlying_count"] = len(RAPID_BACKTEST_IDS)
    composite_daily.to_csv(composite_root / "combined_portfolio_daily_returns.csv", index=False)
    composite_daily.to_csv(artifact_root / "combined_portfolio_daily_returns.csv", index=False)
    composite_daily.to_csv(composite_root / "strategy_21_daily_returns.csv", index=False)
    composite_daily.to_csv(artifact_root / "strategy_21_daily_returns.csv", index=False)
    (artifact_root / "combined_portfolio_summary.json").write_text(json.dumps(composite_summary, indent=2), encoding="utf-8")
    (composite_root / "combined_portfolio_summary.json").write_text(json.dumps(composite_summary, indent=2), encoding="utf-8")
    (artifact_root / "strategy21_summary.json").write_text(json.dumps(composite_summary, indent=2), encoding="utf-8")
    (composite_root / "strategy_21_summary.json").write_text(json.dumps(composite_summary, indent=2), encoding="utf-8")

    export_current_holdings(factory_root, RAPID_BACKTEST_IDS).to_csv(artifact_root / "current_holdings.csv", index=False)
    pd.DataFrame(active_pair_rows).to_csv(composite_root / "candidate_pairwise_analysis.csv", index=False)
    (composite_root / "candidate_overlap_summary.json").write_text(
        json.dumps(
            {
                "composite_id": COMPOSITE_ID,
                "tested_underlying_ids": list(RAPID_BACKTEST_IDS),
                "active_member_ids": list(active_ids),
                "eligible_member_ids": list(active_ids),
                "reference_only_ids": list(reference_ids),
                "replacement_notes": replacement_notes,
                "dynamic_membership": True,
                "N": composite_summary["N"],
                "equal_weight": composite_summary["equal_weight"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    chart_paths = write_combined_portfolio_charts(composite_daily, active_corr, artifact_root, composite_root)
    write_evidence_manifest(artifact_root, composite_root, leaderboard, composite_summary, chart_paths)
    write_combined_portfolio_report(
        artifact_root / "combined_portfolio_report.md", leaderboard, composite_summary, active_pair_rows, chart_paths
    )
    write_summary_markdown(artifact_root / "rapid_20plus1_summary.md", leaderboard, composite_summary, active_pair_rows)
    return {
        "leaderboard": leaderboard,
        "composite_summary": composite_summary,
        "returns": active_net,
        "active_ids": active_ids,
        "reference_ids": reference_ids,
        "pair_rows": active_pair_rows,
        "replacement_notes": replacement_notes,
        "artifact_root": artifact_root,
    }
