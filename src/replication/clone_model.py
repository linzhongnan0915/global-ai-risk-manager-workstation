"""Linear hedge fund replication clone model.

The model follows the boss-provided hedge fund replication paper at a
prototype level: regress a target return stream on liquid factor proxies,
separate common factor beta from residual alpha, and build a rolling clone
without using future returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.risk.performance import max_drawdown, sharpe_ratio, volatility


FACTOR_PROXIES = {
    "SP500": "SPY",
    "BOND": "IEF",
    "USD": "UUP",
    "CREDIT": "HYG",
    "CMDTY": "DBC",
    "DVIX": "VIX",
}


@dataclass(frozen=True)
class ReplicationResult:
    target_id: str
    target_name: str
    method: str
    observations: int
    alpha_daily: float
    alpha_annualized: float
    r_squared: float
    betas: dict[str, float]
    target_metrics: dict[str, float]
    clone_metrics: dict[str, float]
    residual_metrics: dict[str, float]
    clone_gap: dict[str, float]
    warnings: list[str]


def load_factor_returns(price_path: str | Path = "data/processed/market_price_history.csv") -> pd.DataFrame:
    panel = pd.read_csv(price_path)
    if panel.empty:
        raise ValueError("price history is empty")
    panel["date"] = pd.to_datetime(panel["date"])
    prices = panel.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    returns = prices.pct_change(fill_method=None)
    factors = pd.DataFrame(index=returns.index)
    for factor, ticker in FACTOR_PROXIES.items():
        if ticker not in returns.columns:
            continue
        if factor == "DVIX":
            # Paper uses first difference of VIX level. Scale by 100 so beta is readable.
            vix = prices[ticker].diff() / 100.0
            factors[factor] = vix
        else:
            factors[factor] = returns[ticker]
    return factors.dropna(how="all")


def equal_weight_target_returns(
    target_tickers: list[str],
    price_path: str | Path = "data/processed/market_price_history.csv",
) -> pd.Series:
    panel = pd.read_csv(price_path)
    panel["date"] = pd.to_datetime(panel["date"])
    prices = panel.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    returns = prices.pct_change(fill_method=None)
    usable = [ticker.replace("^VIX", "VIX") for ticker in target_tickers if ticker.replace("^VIX", "VIX") in returns.columns]
    if not usable:
        raise ValueError("target_tickers have no overlap with price history")
    return returns[usable].mean(axis=1, skipna=True).dropna()


def run_fixed_replication(
    target_returns: pd.Series,
    factor_returns: pd.DataFrame,
    target_id: str,
    target_name: str,
) -> ReplicationResult:
    data = _aligned_data(target_returns, factor_returns)
    y = data["target"].to_numpy(dtype=float)
    x = data.drop(columns=["target"]).to_numpy(dtype=float)
    alpha, betas_arr = _ols_with_intercept(y, x)
    clone = alpha + x @ betas_arr
    residual = y - clone
    factor_names = list(data.drop(columns=["target"]).columns)
    return _build_result(
        target_id=target_id,
        target_name=target_name,
        method="fixed_full_sample_explanatory",
        y=y,
        clone=clone,
        residual=residual,
        alpha=alpha,
        betas=dict(zip(factor_names, betas_arr)),
        extra_warnings=["Fixed full-sample clone is explanatory only because it uses future data."],
    )


def run_rolling_replication(
    target_returns: pd.Series,
    factor_returns: pd.DataFrame,
    target_id: str,
    target_name: str,
    window: int = 126,
) -> ReplicationResult:
    data = _aligned_data(target_returns, factor_returns)
    if len(data) <= window:
        raise ValueError(f"need more than {window} observations for rolling clone")
    factor_names = list(data.drop(columns=["target"]).columns)
    clones = []
    actuals = []
    residuals = []
    beta_history = []
    alpha_history = []
    values = data.to_numpy(dtype=float)
    for end in range(window, len(data)):
        train = values[end - window : end]
        current = values[end]
        y_train = train[:, 0]
        x_train = train[:, 1:]
        alpha, betas_arr = _ols_with_intercept(y_train, x_train)
        clone_value = alpha + current[1:] @ betas_arr
        actual = current[0]
        clones.append(float(clone_value))
        actuals.append(float(actual))
        residuals.append(float(actual - clone_value))
        beta_history.append(betas_arr)
        alpha_history.append(alpha)
    avg_betas = np.mean(np.vstack(beta_history), axis=0)
    avg_alpha = float(np.mean(alpha_history))
    return _build_result(
        target_id=target_id,
        target_name=target_name,
        method=f"rolling_{window}_day_no_lookahead",
        y=np.array(actuals),
        clone=np.array(clones),
        residual=np.array(residuals),
        alpha=avg_alpha,
        betas=dict(zip(factor_names, avg_betas)),
        extra_warnings=[],
    )


def result_to_dict(result: ReplicationResult) -> dict:
    return {
        "target_id": result.target_id,
        "target_name": result.target_name,
        "method": result.method,
        "observations": result.observations,
        "alpha_daily": result.alpha_daily,
        "alpha_annualized": result.alpha_annualized,
        "r_squared": result.r_squared,
        "betas": result.betas,
        "target_metrics": result.target_metrics,
        "clone_metrics": result.clone_metrics,
        "residual_metrics": result.residual_metrics,
        "clone_gap": result.clone_gap,
        "warnings": result.warnings,
    }


def _aligned_data(target_returns: pd.Series, factor_returns: pd.DataFrame) -> pd.DataFrame:
    data = pd.concat([target_returns.rename("target"), factor_returns], axis=1).dropna()
    if len(data) < 30:
        raise ValueError("not enough overlapping target/factor returns")
    return data


def _ols_with_intercept(y: np.ndarray, x: np.ndarray) -> tuple[float, np.ndarray]:
    design = np.column_stack([np.ones(len(y)), x])
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(coeffs[0]), coeffs[1:]


def _metrics(values: np.ndarray) -> dict[str, float]:
    returns = [float(value) for value in values]
    return {
        "annual_return": float(np.prod(1.0 + values) ** (252 / len(values)) - 1.0),
        "annual_volatility": volatility(returns),
        "sharpe": sharpe_ratio(returns),
        "max_drawdown": max_drawdown(returns),
    }


def _build_result(
    target_id: str,
    target_name: str,
    method: str,
    y: np.ndarray,
    clone: np.ndarray,
    residual: np.ndarray,
    alpha: float,
    betas: dict[str, float],
    extra_warnings: list[str],
) -> ReplicationResult:
    ss_res = float(np.sum((y - clone) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    target_metrics = _metrics(y)
    clone_metrics = _metrics(clone)
    residual_metrics = _metrics(residual)
    warnings = list(extra_warnings)
    if r_squared > 0.7:
        warnings.append("High R-squared: target is largely explained by common liquid factors.")
    elif r_squared < 0.25:
        warnings.append("Low R-squared: target may include idiosyncratic alpha, illiquidity premium, or missing factors.")
    if abs(clone_metrics["sharpe"] - target_metrics["sharpe"]) > 0.75:
        warnings.append("Large Sharpe gap between target and clone; review proxy mismatch or residual alpha.")
    if residual_metrics["annual_volatility"] > target_metrics["annual_volatility"] * 0.6:
        warnings.append("Residual volatility is large relative to target; clone may be incomplete.")
    return ReplicationResult(
        target_id=target_id,
        target_name=target_name,
        method=method,
        observations=len(y),
        alpha_daily=float(alpha),
        alpha_annualized=float(alpha * 252),
        r_squared=float(r_squared),
        betas={key: float(value) for key, value in betas.items()},
        target_metrics=target_metrics,
        clone_metrics=clone_metrics,
        residual_metrics=residual_metrics,
        clone_gap={
            "annual_return_gap": target_metrics["annual_return"] - clone_metrics["annual_return"],
            "sharpe_gap": target_metrics["sharpe"] - clone_metrics["sharpe"],
            "max_drawdown_gap": target_metrics["max_drawdown"] - clone_metrics["max_drawdown"],
        },
        warnings=warnings,
    )
