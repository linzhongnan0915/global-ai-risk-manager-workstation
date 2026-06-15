"""End-to-end WorldQuant Alpha #2 research backtest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.risk.performance import cumulative_returns, max_drawdown, sharpe_ratio, volatility
from src.strategies.worldquant.alpha2 import compute_alpha2_components
from src.strategies.worldquant.data_loader import prepare_alpha2_market_data
from src.strategies.worldquant.market_data import (
    DEFAULT_CORRELATION_WINDOW,
    DEFAULT_DELTA_PERIODS,
    DEFAULT_MIN_ALPHA2_OBSERVATIONS,
    is_usable_ticker_status,
    merge_download_failures_into_quality_report,
)
from src.strategies.worldquant.portfolio import signal_to_dollar_neutral_weights
from src.strategies.worldquant.portfolio_returns import (
    EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
    PortfolioReturnResult,
    build_asset_return_panel,
    compute_portfolio_returns_from_weights,
    resolve_execution_spec,
    validate_execution_mode,
)

STRATEGY_NAME = "WorldQuant Alpha #2"
TRADING_DAYS = 252
DEFAULT_BUY_BPS = 5.0
DEFAULT_SELL_BPS = 5.0
DEFAULT_GROSS_EXPOSURE_TARGET = 1.0
DEFAULT_NET_EXPOSURE_TARGET = 0.0


@dataclass(frozen=True)
class Alpha2BacktestResult:
    run_status: str
    summary: pd.DataFrame
    daily_returns: pd.DataFrame
    quality_report: pd.DataFrame
    signal_sample: pd.DataFrame
    components: dict[str, pd.DataFrame]
    weights: pd.DataFrame
    signal: pd.DataFrame
    executed_weights: pd.DataFrame
    portfolio_returns: PortfolioReturnResult | None


def _compound_return(values: pd.Series) -> float:
    clean = values.dropna().astype(float)
    if clean.empty:
        return 0.0
    return float(np.prod(1.0 + clean.to_numpy()) - 1.0)


def _active_backtest_index(weights: pd.DataFrame) -> pd.Index:
    active = weights.abs().sum(axis=1) > 1e-10
    if not active.any():
        return weights.index[:0]
    return weights.loc[active[active].index[0] :].index


def _execution_date_for_signal(
    index: pd.DatetimeIndex,
    signal_date: pd.Timestamp,
    execution_lag: int,
) -> pd.Timestamp | None:
    position = index.get_loc(signal_date)
    if isinstance(position, slice):
        position = position.start
    execution_position = int(position) + execution_lag
    if execution_position >= len(index):
        return None
    return index[execution_position]


def _position_side(weight: float) -> str:
    if weight > 0:
        return "long"
    if weight < 0:
        return "short"
    return "not_selected"


def _build_summary_row(
    *,
    run_status: str,
    requested_tickers: list[str],
    usable_ticker_count: int,
    quality_report: pd.DataFrame,
    net: pd.Series,
    gross: pd.Series,
    turnover: pd.Series,
    execution_mode: str,
    execution_lag: int,
    return_definition: str,
    long_quantile: float,
    short_quantile: float,
    buy_bps: float,
    sell_bps: float,
    requested_start_date: str | None,
    requested_end_date: str | None,
    actual_data_start_date: str | None,
    actual_data_end_date: str | None,
) -> dict[str, Any]:
    valid_days = int(net.dropna().shape[0])
    net_values = net.dropna().astype(float).tolist()
    return {
        "strategy_name": STRATEGY_NAME,
        "run_status": run_status,
        "requested_ticker_count": len(requested_tickers),
        "usable_ticker_count": usable_ticker_count,
        "rejected_ticker_count": int((~quality_report["status"].map(is_usable_ticker_status)).sum()),
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
        "actual_data_start_date": actual_data_start_date,
        "actual_data_end_date": actual_data_end_date,
        "start_date": net.index[0].date().isoformat() if valid_days else None,
        "end_date": net.index[-1].date().isoformat() if valid_days else None,
        "valid_trading_days": valid_days,
        "execution_mode": execution_mode,
        "execution_lag": execution_lag,
        "return_definition": return_definition,
        "long_quantile": long_quantile,
        "short_quantile": short_quantile,
        "buy_bps": buy_bps,
        "sell_bps": sell_bps,
        "gross_exposure_target": DEFAULT_GROSS_EXPOSURE_TARGET,
        "net_exposure_target": DEFAULT_NET_EXPOSURE_TARGET,
        "annualized_return": float((np.prod([1 + value for value in net_values]) ** (TRADING_DAYS / valid_days)) - 1)
        if valid_days
        else 0.0,
        "annualized_volatility": volatility(net_values) if len(net_values) > 1 else 0.0,
        "sharpe_ratio": sharpe_ratio(net_values) if len(net_values) > 1 else 0.0,
        "maximum_drawdown": max_drawdown(net_values) if net_values else 0.0,
        "cumulative_gross_return": _compound_return(gross),
        "cumulative_net_return": _compound_return(net),
        "average_daily_turnover": float(turnover.mean()) if valid_days else 0.0,
        "data_coverage": float(usable_ticker_count / max(len(requested_tickers), 1)),
    }


def run_alpha2_backtest(
    ohlcv: pd.DataFrame,
    requested_tickers: list[str],
    *,
    delta_periods: int = DEFAULT_DELTA_PERIODS,
    correlation_window: int = DEFAULT_CORRELATION_WINDOW,
    min_valid_observations: int = DEFAULT_MIN_ALPHA2_OBSERVATIONS,
    long_quantile: float = 0.20,
    short_quantile: float = 0.20,
    execution_mode: str = EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
    buy_bps: float = DEFAULT_BUY_BPS,
    sell_bps: float = DEFAULT_SELL_BPS,
    download_failures: pd.DataFrame | None = None,
    requested_start_date: str | None = None,
    requested_end_date: str | None = None,
    actual_data_start_date: str | None = None,
    actual_data_end_date: str | None = None,
) -> Alpha2BacktestResult:
    """Run Alpha #2 signal -> delayed weights -> gross/net daily returns."""
    execution_mode = validate_execution_mode(execution_mode)
    execution_lag, return_definition = resolve_execution_spec(execution_mode)

    panels, usable_ohlcv, quality_report = prepare_alpha2_market_data(
        ohlcv,
        requested_tickers,
        min_valid_observations=min_valid_observations,
    )
    quality_report = merge_download_failures_into_quality_report(quality_report, download_failures)
    usable_tickers = sorted(
        quality_report.loc[quality_report["status"].map(is_usable_ticker_status), "ticker"].tolist()
    )

    if actual_data_start_date is None and not ohlcv.empty:
        actual_data_start_date = pd.to_datetime(ohlcv["date"]).min().date().isoformat()
        actual_data_end_date = pd.to_datetime(ohlcv["date"]).max().date().isoformat()

    summary_kwargs = dict(
        requested_tickers=requested_tickers,
        usable_ticker_count=len(usable_tickers),
        quality_report=quality_report,
        execution_mode=execution_mode,
        execution_lag=execution_lag,
        return_definition=return_definition,
        long_quantile=long_quantile,
        short_quantile=short_quantile,
        buy_bps=buy_bps,
        sell_bps=sell_bps,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        actual_data_start_date=actual_data_start_date,
        actual_data_end_date=actual_data_end_date,
    )

    if not usable_tickers:
        empty_net = pd.Series(dtype=float)
        empty_gross = pd.Series(dtype=float)
        empty_turnover = pd.Series(dtype=float)
        return Alpha2BacktestResult(
            run_status="failed_no_usable_data",
            summary=pd.DataFrame(
                [_build_summary_row(
                    run_status="failed_no_usable_data",
                    net=empty_net,
                    gross=empty_gross,
                    turnover=empty_turnover,
                    **summary_kwargs,
                )]
            ),
            daily_returns=pd.DataFrame(
                columns=["date", "gross_return", "transaction_cost", "net_return", "cumulative_net_value"]
            ),
            quality_report=quality_report,
            signal_sample=pd.DataFrame(),
            components={},
            weights=pd.DataFrame(),
            signal=pd.DataFrame(),
            executed_weights=pd.DataFrame(),
            portfolio_returns=None,
        )

    open_prices = panels["open"]
    close_prices = panels["close"]
    volume = panels["volume"]
    adj_close = panels["adj_close"]

    components = compute_alpha2_components(
        open_prices,
        close_prices,
        volume,
        delta_periods=delta_periods,
        correlation_window=correlation_window,
    )
    signal = components["alpha"]
    target_weights = signal_to_dollar_neutral_weights(
        signal,
        long_quantile=long_quantile,
        short_quantile=short_quantile,
    )

    asset_returns = build_asset_return_panel(
        open_prices,
        close_prices,
        adj_close,
        execution_mode=execution_mode,
    )
    portfolio_returns = compute_portfolio_returns_from_weights(
        target_weights,
        asset_returns,
        execution_lag=execution_lag,
        buy_bps=buy_bps,
        sell_bps=sell_bps,
        return_definition=return_definition,
    )

    active_index = _active_backtest_index(portfolio_returns.executed_weights)
    if active_index.empty:
        return Alpha2BacktestResult(
            run_status="failed_no_active_positions",
            summary=pd.DataFrame(
                [_build_summary_row(
                    run_status="failed_no_active_positions",
                    net=portfolio_returns.net_return,
                    gross=portfolio_returns.gross_return,
                    turnover=portfolio_returns.turnover,
                    **summary_kwargs,
                )]
            ),
            daily_returns=pd.DataFrame(
                columns=["date", "gross_return", "transaction_cost", "net_return", "cumulative_net_value"]
            ),
            quality_report=quality_report,
            signal_sample=_build_signal_sample(
                components,
                signal,
                target_weights,
                portfolio_returns.executed_weights,
                execution_mode=execution_mode,
                execution_lag=execution_lag,
                max_rows=120,
            ),
            components=components,
            weights=target_weights,
            signal=signal,
            executed_weights=portfolio_returns.executed_weights,
            portfolio_returns=portfolio_returns,
        )

    gross = portfolio_returns.gross_return.loc[active_index]
    turnover = portfolio_returns.turnover.loc[active_index]
    transaction_cost = portfolio_returns.transaction_cost.loc[active_index]
    net = portfolio_returns.net_return.loc[active_index]

    cumulative_net = cumulative_returns(net.tolist())
    daily_returns = pd.DataFrame(
        {
            "date": [idx.date().isoformat() for idx in net.index],
            "gross_return": gross.to_numpy(dtype=float),
            "transaction_cost": transaction_cost.to_numpy(dtype=float),
            "net_return": net.to_numpy(dtype=float),
            "cumulative_net_value": [1.0 + value for value in cumulative_net],
        }
    )

    summary = pd.DataFrame(
        [_build_summary_row(
            run_status="completed",
            net=net,
            gross=gross,
            turnover=turnover,
            **summary_kwargs,
        )]
    )

    signal_sample = _build_signal_sample(
        components,
        signal,
        target_weights,
        portfolio_returns.executed_weights,
        execution_mode=execution_mode,
        execution_lag=execution_lag,
        max_rows=120,
    )

    return Alpha2BacktestResult(
        run_status="completed",
        summary=summary,
        daily_returns=daily_returns,
        quality_report=quality_report,
        signal_sample=signal_sample,
        components=components,
        weights=target_weights,
        signal=signal,
        executed_weights=portfolio_returns.executed_weights,
        portfolio_returns=portfolio_returns,
    )


def _build_signal_sample(
    components: dict[str, pd.DataFrame],
    signal: pd.DataFrame,
    target_weights: pd.DataFrame,
    executed_weights: pd.DataFrame,
    *,
    execution_mode: str,
    execution_lag: int,
    max_rows: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal_date in signal.index:
        row = signal.loc[signal_date].dropna()
        if row.empty:
            continue

        ranked = row.sort_values(ascending=False)
        selected = list(ranked.head(2).index) + list(ranked.tail(2).index)
        execution_date = _execution_date_for_signal(signal.index, signal_date, execution_lag)

        for ticker in selected:
            target_position = float(target_weights.loc[signal_date, ticker])
            executed_position = (
                float(executed_weights.loc[execution_date, ticker])
                if execution_date is not None and ticker in executed_weights.columns
                else 0.0
            )
            rows.append(
                {
                    "signal_date": signal_date.date().isoformat(),
                    "execution_date": execution_date.date().isoformat() if execution_date is not None else "",
                    "ticker": ticker,
                    "side": _position_side(target_position),
                    "volume_delta_rank": float(components["volume_delta_rank"].loc[signal_date, ticker]),
                    "intraday_return_rank": float(components["intraday_return_rank"].loc[signal_date, ticker]),
                    "rolling_correlation": float(components["rolling_correlation"].loc[signal_date, ticker]),
                    "signal": float(signal.loc[signal_date, ticker]),
                    "target_position": target_position,
                    "executed_position": executed_position,
                    "execution_mode": execution_mode,
                }
            )
        if len(rows) >= max_rows:
            break
    return pd.DataFrame(rows)


def write_alpha2_backtest_outputs(
    result: Alpha2BacktestResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write the minimum Alpha #2 research output package."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "strategy_summary": out / "strategy_summary.csv",
        "daily_strategy_returns": out / "daily_strategy_returns.csv",
        "data_quality_report": out / "data_quality_report.csv",
        "signal_sample": out / "signal_sample.csv",
    }
    result.summary.to_csv(paths["strategy_summary"], index=False)
    result.daily_returns.to_csv(paths["daily_strategy_returns"], index=False)
    result.quality_report.to_csv(paths["data_quality_report"], index=False)
    result.signal_sample.to_csv(paths["signal_sample"], index=False)
    return paths
