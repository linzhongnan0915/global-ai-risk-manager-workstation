"""Minimal reusable OHLCV strategy screening engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import json

import numpy as np
import pandas as pd

from src.risk.performance import cumulative_returns, drawdown_series, max_drawdown, sharpe_ratio, volatility
from src.strategies.worldquant.data_loader import load_ohlcv_csv, ohlcv_long_to_panels
from src.strategies.worldquant.portfolio_returns import (
    EXECUTION_MODE_NEXT_OPEN_TO_OPEN,
    EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
    build_asset_return_panel,
    compute_portfolio_returns_from_weights,
    resolve_execution_spec,
)


@dataclass(frozen=True)
class StrategyContext:
    panels: dict[str, pd.DataFrame]
    daily_returns: pd.DataFrame
    market_return: pd.Series
    lagged_beta: pd.DataFrame
    lagged_adv: pd.DataFrame


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    version: str
    name: str
    hypothesis: str
    signal_function: Callable[[StrategyContext], pd.DataFrame]
    rebalance_every: int
    min_price: float = 5.0
    min_lagged_adv: float = 5_000_000.0
    min_cross_section: int = 100
    side_fraction: float = 0.20
    total_gross: float = 1.0
    buy_bps: float = 5.0
    sell_bps: float = 5.0
    execution_mode: str = EXECUTION_MODE_NEXT_OPEN_TO_OPEN
    require_beta_history: bool = False
    max_missing_execution_exposure_ratio: float = 0.001


def load_context(ohlcv_path: str | Path, beta_lookback: int = 60, adv_lookback: int = 20) -> StrategyContext:
    panels = ohlcv_long_to_panels(
        load_ohlcv_csv(ohlcv_path),
        value_columns=("open", "high", "low", "close", "volume", "adj_close"),
    )
    daily_returns = panels["adj_close"].pct_change(fill_method=None)
    market_return = daily_returns.mean(axis=1, skipna=True)
    market_variance = market_return.rolling(beta_lookback, min_periods=beta_lookback).var()
    beta = daily_returns.rolling(beta_lookback, min_periods=beta_lookback).cov(market_return)
    lagged_beta = beta.div(market_variance, axis=0).shift(1)
    lagged_adv = panels["close"].mul(panels["volume"]).rolling(
        adv_lookback, min_periods=adv_lookback
    ).mean().shift(1)
    return StrategyContext(panels, daily_returns, market_return, lagged_beta, lagged_adv)


def build_execution_returns(context: StrategyContext, spec: StrategySpec) -> tuple[pd.DataFrame, int, str]:
    """Build returns and timing from the same execution-mode contract."""
    execution_lag, return_definition = resolve_execution_spec(spec.execution_mode)
    returns = build_asset_return_panel(
        context.panels["open"], context.panels["close"], context.panels["adj_close"],
        execution_mode=spec.execution_mode,
    )
    return returns, execution_lag, return_definition


def common_eligibility(score: pd.DataFrame, context: StrategyContext, spec: StrategySpec) -> pd.DataFrame:
    eligible = (
        score.notna()
        & context.panels["close"].ge(spec.min_price)
        & context.lagged_adv.ge(spec.min_lagged_adv)
    )
    return eligible & context.lagged_beta.notna() if spec.require_beta_history else eligible


def rank_and_weight(
    score: pd.DataFrame, eligible: pd.DataFrame, spec: StrategySpec
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights = pd.DataFrame(0.0, index=score.index, columns=score.columns)
    rows: list[dict[str, object]] = []
    current = pd.Series(0.0, index=score.columns)
    valid_day_number = 0
    for date in score.index:
        valid = eligible.loc[date] & score.loc[date].notna()
        count = int(valid.sum())
        rebalance = count >= spec.min_cross_section and valid_day_number % spec.rebalance_every == 0
        if count >= spec.min_cross_section:
            valid_day_number += 1
        if rebalance:
            ranked = score.loc[date, valid].sort_values()
            side_count = max(1, int(np.floor(count * spec.side_fraction)))
            current = pd.Series(0.0, index=score.columns)
            current.loc[ranked.head(side_count).index] = -spec.total_gross / 2.0 / side_count
            current.loc[ranked.tail(side_count).index] = spec.total_gross / 2.0 / side_count
        weights.loc[date] = current
        rows.append(
            {
                "date": date, "eligible_count": count, "rebalance": rebalance,
                "long_count": int((current > 0).sum()), "short_count": int((current < 0).sum()),
                "long_exposure": float(current.clip(lower=0).sum()),
                "short_exposure": float(current.clip(upper=0).sum()),
                "gross_exposure": float(current.abs().sum()), "net_exposure": float(current.sum()),
            }
        )
    return weights, pd.DataFrame(rows)


def signal_diagnostics(
    score: pd.DataFrame, eligible: pd.DataFrame, forward_returns: pd.DataFrame, dates: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ic_rows: list[dict[str, object]] = []
    decile_rows: list[dict[str, object]] = []
    for date in dates:
        valid = eligible.loc[date] & score.loc[date].notna() & forward_returns.loc[date].notna()
        signal = score.loc[date, valid]
        future = forward_returns.loc[date, valid]
        ic_rows.append(
            {"date": date, "ic": signal.rank().corr(future.rank()), "evaluated_count": int(valid.sum())}
        )
        if valid.sum() >= 10:
            buckets = pd.qcut(signal.rank(method="first"), 10, labels=False) + 1
            for decile, value in future.groupby(buckets).mean().items():
                decile_rows.append({"date": date, "decile": int(decile), "forward_return": float(value)})
    return pd.DataFrame(ic_rows), pd.DataFrame(decile_rows)


def build_missing_execution_records(
    executed_weights: pd.DataFrame, asset_returns: pd.DataFrame, spec: StrategySpec
) -> tuple[pd.DataFrame, dict[str, object]]:
    missing = executed_weights.ne(0.0) & asset_returns.isna()
    rows: list[dict[str, object]] = []
    for date, ticker in zip(*np.where(missing.to_numpy())):
        execution_date = executed_weights.index[date]
        symbol = executed_weights.columns[ticker]
        if spec.execution_mode == EXECUTION_MODE_NEXT_OPEN_TO_CLOSE:
            reason = "missing_execution_open_or_close"
        elif spec.execution_mode == EXECUTION_MODE_NEXT_OPEN_TO_OPEN:
            reason = "missing_execution_next_open"
        else:
            reason = "missing_execution_adjusted_close_return"
        weight = float(executed_weights.iloc[date, ticker])
        rows.append(
            {
                "date": execution_date, "ticker": symbol, "target_weight": weight,
                "missing_return_reason": reason, "affected_absolute_exposure": abs(weight),
            }
        )
    records = pd.DataFrame(
        rows,
        columns=["date", "ticker", "target_weight", "missing_return_reason", "affected_absolute_exposure"],
    )
    affected = float(records["affected_absolute_exposure"].sum()) if not records.empty else 0.0
    total = float(executed_weights.abs().sum().sum())
    ratio = affected / total if total > 0 else 0.0
    return records, {
        "missing_execution_return_count": len(records),
        "total_affected_absolute_exposure": affected,
        "total_executed_absolute_exposure": total,
        "affected_exposure_ratio": ratio,
        "invalidation_threshold": spec.max_missing_execution_exposure_ratio,
        "run_valid": ratio <= spec.max_missing_execution_exposure_ratio,
    }


def build_rebalance_audit(
    score: pd.DataFrame, eligible: pd.DataFrame, target: pd.DataFrame, context: StrategyContext,
    asset_returns: pd.DataFrame, positions: pd.DataFrame, execution_lag: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = list(score.index)
    for signal_date in pd.to_datetime(positions.loc[positions["rebalance"], "date"]):
        execution_position = dates.index(signal_date) + execution_lag
        execution_date = dates[execution_position] if execution_position < len(dates) else None
        valid_scores = score.loc[signal_date, eligible.loc[signal_date]].sort_values()
        ranks = valid_scores.rank(method="first", pct=True)
        deciles = pd.qcut(valid_scores.rank(method="first"), 10, labels=False) + 1
        for ticker in valid_scores.index:
            available = bool(
                execution_date is not None and pd.notna(asset_returns.loc[execution_date, ticker])
            )
            rows.append(
                {
                    "date": signal_date, "ticker": ticker, "score": float(valid_scores[ticker]),
                    "rank": float(ranks[ticker]), "decile": int(deciles[ticker]),
                    "target_weight": float(target.loc[signal_date, ticker]),
                    "lagged_beta": float(context.lagged_beta.loc[signal_date, ticker]),
                    "lagged_adv": float(context.lagged_adv.loc[signal_date, ticker]),
                    "execution_return_available": available,
                }
            )
    return pd.DataFrame(rows)


def _summary(
    spec: StrategySpec, daily: pd.DataFrame, ic: pd.DataFrame, deciles: pd.DataFrame,
    missing_summary: dict[str, object],
) -> dict[str, object]:
    decile_means = deciles.groupby("decile")["forward_return"].mean()
    spread = float(decile_means.get(10, np.nan) - decile_means.get(1, np.nan))
    valid_daily = daily.dropna(subset=["net_return", "gross_return"])
    net_series = valid_daily["net_return"]
    gross_total = float(valid_daily["gross_return"].sum())
    cost_total = float(valid_daily["transaction_cost"].sum())
    gates = {
        "positive_mean_ic": bool(ic["ic"].mean() > 0),
        "positive_d10_minus_d1": bool(spread > 0),
        "positive_gross_edge": bool(gross_total > 0),
        "gross_edge_exceeds_cost": bool(gross_total > cost_total),
    }
    run_valid = bool(missing_summary["run_valid"])
    return {
        "strategy_id": spec.strategy_id, "version": spec.version,
        "decision": "CONTINUE" if run_valid and all(gates.values()) else "ARCHIVE",
        "run_valid": run_valid,
        "hypothetical_backfill": True, "survivorship_biased_current_listed_universe": True,
        "execution_mode": spec.execution_mode,
        "observations": len(valid_daily), "cumulative_gross_return": float(valid_daily["cumulative_gross"].iloc[-1]),
        "cumulative_net_return": float(valid_daily["cumulative_net"].iloc[-1]), "gross_return_sum": gross_total,
        "transaction_cost_sum": cost_total, "cost_drag_ratio": float(cost_total / gross_total) if gross_total > 0 else None,
        "annualized_net_volatility": float(volatility(net_series)),
        "net_sharpe": float(sharpe_ratio(net_series)), "max_drawdown": float(max_drawdown(net_series)),
        "average_daily_turnover": float(valid_daily["turnover"].mean()), "mean_ic": float(ic["ic"].mean()),
        "d10_minus_d1": spread, "decision_gates": gates,
        "missing_execution_returns": missing_summary,
        "reconciliation": {
            "max_abs_gross_minus_long_short": float((daily["gross_return"] - daily["long_contribution"] - daily["short_contribution"]).abs().max()),
            "max_abs_gross_minus_cost_minus_net": float((daily["gross_return"] - daily["transaction_cost"] - daily["net_return"]).abs().max()),
            "max_abs_long_plus_short_gross_exposure": float((daily["long_exposure"] - daily["short_exposure"] - daily["gross_exposure"]).abs().max()),
        },
        "accounting_rule": (
            "Missing execution returns remain zero placeholders in PnL accounting but are separately "
            "exported and invalidate the run when affected exposure exceeds the configured threshold."
        ),
    }


def _write_outputs(
    output_dir: Path, spec: StrategySpec, summary: dict[str, object], daily: pd.DataFrame,
    positions: pd.DataFrame, ic: pd.DataFrame, deciles: pd.DataFrame,
    missing_records: pd.DataFrame, rebalance_audit: pd.DataFrame,
) -> None:
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    daily.to_csv(output_dir / "daily_returns.csv", index=False)
    positions.to_csv(output_dir / "positions_summary.csv", index=False)
    missing_records.to_csv(output_dir / "missing_execution_returns.csv", index=False)
    rebalance_audit.to_csv(output_dir / "rebalance_audit.csv", index=False)
    decile_means = deciles.groupby("decile", as_index=False)["forward_return"].mean()
    signal_summary = pd.concat(
        [
            pd.DataFrame([{"metric": "mean_ic", "value": ic["ic"].mean()}]),
            decile_means.rename(columns={"decile": "metric", "forward_return": "value"}).assign(
                metric=lambda x: "decile_" + x["metric"].astype(str)
            ),
        ],
        ignore_index=True,
    )
    signal_summary.to_csv(output_dir / "ic_decile_summary.csv", index=False)
    daily.plot(x="date", y=["cumulative_gross", "cumulative_net"], title=f"{spec.strategy_id} Equity Curve")
    plt.tight_layout(); plt.savefig(output_dir / "equity_curve.png", dpi=140); plt.close()
    daily.plot(x="date", y="drawdown", title=f"{spec.strategy_id} Drawdown")
    plt.tight_layout(); plt.savefig(output_dir / "drawdown.png", dpi=140); plt.close()
    decile_means.plot(x="decile", y="forward_return", kind="bar", title=f"{spec.strategy_id} Deciles")
    plt.tight_layout(); plt.savefig(output_dir / "decile_chart.png", dpi=140); plt.close()
    report = (
        f"# {spec.strategy_id} Screening Report\n\n"
        f"Decision: **{summary['decision']}**\n\n"
        f"Hypothesis: {spec.hypothesis}\n\n"
        f"Mean IC: {summary['mean_ic']:.6f}; D10-D1: {summary['d10_minus_d1']:.6f}; "
        f"gross sum: {summary['gross_return_sum']:.4f}; cost sum: {summary['transaction_cost_sum']:.4f}; "
        f"net Sharpe: {summary['net_sharpe']:.3f}.\n\n"
        f"Run valid: **{summary['run_valid']}**. Missing execution returns: "
        f"{summary['missing_execution_returns']['missing_execution_return_count']}; affected exposure ratio: "
        f"{summary['missing_execution_returns']['affected_exposure_ratio']:.6%}.\n\n"
        "Signals use information through the prior close; positions are active from open[t] "
        "through open[t+1] with open-to-open holding returns. "
        "Eligibility does not use future-return availability. Results are hypothetical and survivorship biased.\n"
    )
    (output_dir / "screening_report.md").write_text(report, encoding="utf-8")


def run_strategy(spec: StrategySpec, context: StrategyContext, output_dir: str | Path) -> dict[str, object]:
    score = spec.signal_function(context)
    eligible = common_eligibility(score, context, spec)
    target, positions = rank_and_weight(score, eligible, spec)
    asset_returns, execution_lag, return_definition = build_execution_returns(context, spec)
    result = compute_portfolio_returns_from_weights(
        target, asset_returns, execution_lag=execution_lag, buy_bps=spec.buy_bps,
        sell_bps=spec.sell_bps, return_definition=return_definition,
    )
    rebalance_dates = pd.DatetimeIndex(pd.to_datetime(positions.loc[positions["rebalance"], "date"]))
    ic, deciles = signal_diagnostics(
        score,
        eligible,
        asset_returns if execution_lag == 0 else asset_returns.shift(-execution_lag),
        rebalance_dates,
    )
    missing_records, missing_summary = build_missing_execution_records(result.executed_weights, asset_returns, spec)
    rebalance_audit = build_rebalance_audit(
        score, eligible, target, context, asset_returns, positions, execution_lag
    )
    contributions = result.executed_weights.mul(asset_returns).fillna(0.0)
    daily = pd.DataFrame(
        {
            "date": target.index, "gross_return": result.gross_return, "transaction_cost": result.transaction_cost,
            "net_return": result.net_return, "turnover": result.turnover,
            "long_contribution": contributions.where(result.executed_weights > 0, 0.0).sum(axis=1),
            "short_contribution": contributions.where(result.executed_weights < 0, 0.0).sum(axis=1),
            "long_exposure": result.executed_weights.clip(lower=0).sum(axis=1),
            "short_exposure": result.executed_weights.clip(upper=0).sum(axis=1),
            "gross_exposure": result.executed_weights.abs().sum(axis=1),
        }
    ).reset_index(drop=True)
    daily = daily.dropna(subset=["gross_return", "net_return"])
    daily["cumulative_gross"] = cumulative_returns(daily["gross_return"])
    daily["cumulative_net"] = cumulative_returns(daily["net_return"])
    daily["drawdown"] = drawdown_series(daily["net_return"])
    summary = _summary(spec, daily, ic, deciles, missing_summary)
    _write_outputs(
        Path(output_dir), spec, summary, daily, positions, ic, deciles, missing_records, rebalance_audit
    )
    return summary
