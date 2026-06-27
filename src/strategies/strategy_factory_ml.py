"""Current-run ML diagnostics for Strategy Factory prototype artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import csv
import json
import math

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "momentum_21d",
    "momentum_63d",
    "realized_volatility_21d",
    "drawdown",
    "moving_average_trend_63d",
    "benchmark_return",
    "relative_strength_21d",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _blocked_payload(reason: str, artifacts: dict[str, str]) -> dict[str, Any]:
    ml = {
        "schema_version": "strategy_factory_ml_diagnostics_run_v0",
        "status": "BLOCKED",
        "reason": reason,
        "models": [],
        "feature_importance_available": False,
        "generated_at": _now(),
        "artifacts": artifacts,
    }
    prediction_quality = {
        "schema_version": "strategy_factory_prediction_quality_v0",
        "status": "BLOCKED",
        "reason": reason,
        "metrics": {},
        "generated_at": _now(),
    }
    split = {
        "schema_version": "strategy_factory_train_test_split_v0",
        "status": "BLOCKED",
        "reason": reason,
        "split_method": "chronological_no_shuffle",
        "generated_at": _now(),
    }
    leakage = {
        "schema_version": "strategy_factory_leakage_check_v0",
        "status": "BLOCKED",
        "reason": reason,
        "generated_at": _now(),
    }
    _write_json(Path(artifacts["ml_diagnostics_run"]), ml)
    _write_json(Path(artifacts["prediction_quality"]), prediction_quality)
    _write_json(Path(artifacts["train_test_split"]), split)
    _write_json(Path(artifacts["leakage_check"]), leakage)
    _write_json(Path(artifacts["feature_importance_json"]), {"status": "BLOCKED", "reason": reason, "feature_importance": []})
    _write_csv(Path(artifacts["feature_importance_csv"]), ["feature", "importance", "model", "status"], [])
    return ml


def _build_feature_frame(daily_returns_path: Path) -> pd.DataFrame:
    daily = pd.read_csv(daily_returns_path)
    required = {"date", "net_return", "benchmark_return"}
    missing = required.difference(daily.columns)
    if missing:
        raise ValueError(f"daily_returns.csv missing required columns: {sorted(missing)}")
    data = daily.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["net_return"] = pd.to_numeric(data["net_return"], errors="coerce")
    data["benchmark_return"] = pd.to_numeric(data["benchmark_return"], errors="coerce")
    data = data.dropna(subset=["date", "net_return", "benchmark_return"]).sort_values("date")
    equity = (1.0 + data["net_return"]).cumprod()
    benchmark_equity = (1.0 + data["benchmark_return"]).cumprod()
    data["momentum_21d"] = equity / equity.shift(21) - 1.0
    data["momentum_63d"] = equity / equity.shift(63) - 1.0
    data["realized_volatility_21d"] = data["net_return"].rolling(21, min_periods=21).std() * math.sqrt(252)
    data["drawdown"] = equity / equity.cummax() - 1.0
    data["moving_average_trend_63d"] = equity / equity.rolling(63, min_periods=63).mean() - 1.0
    data["relative_strength_21d"] = (equity / equity.shift(21) - 1.0) - (benchmark_equity / benchmark_equity.shift(21) - 1.0)
    data["target_next_return"] = data["net_return"].shift(-1)
    data["target_next_direction"] = (data["target_next_return"] > 0).astype(int)
    data["target_date"] = data["date"].shift(-1)
    return data.dropna(subset=FEATURE_COLUMNS + ["target_next_return", "target_date"]).reset_index(drop=True)


def _standardize(train_x: np.ndarray, test_x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mean = train_x.mean(axis=0)
    std = train_x.std(axis=0)
    std[std == 0.0] = 1.0
    return (train_x - mean) / std, (test_x - mean) / std, mean, std


def _ols_fit(train_x: np.ndarray, train_y: np.ndarray) -> np.ndarray:
    x = np.column_stack([np.ones(len(train_x)), train_x])
    return np.linalg.pinv(x).dot(train_y)


def _ridge_fit(train_x: np.ndarray, train_y: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    x = np.column_stack([np.ones(len(train_x)), train_x])
    penalty = np.eye(x.shape[1]) * alpha
    penalty[0, 0] = 0.0
    return np.linalg.pinv(x.T.dot(x) + penalty).dot(x.T).dot(train_y)


def _predict_linear(coef: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(x)), x]).dot(coef)


def _logistic_fit(train_x: np.ndarray, train_y: np.ndarray, steps: int = 1200, learning_rate: float = 0.05) -> np.ndarray:
    x = np.column_stack([np.ones(len(train_x)), train_x])
    coef = np.zeros(x.shape[1])
    for _ in range(steps):
        z = np.clip(x.dot(coef), -35, 35)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = x.T.dot(p - train_y) / len(train_y)
        coef -= learning_rate * grad
    return coef


def _predict_logistic(coef: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.column_stack([np.ones(len(x)), x])
    prob = 1.0 / (1.0 + np.exp(-np.clip(matrix.dot(coef), -35, 35)))
    return prob, (prob >= 0.5).astype(int)


def _quality_regression(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    err = pred - y
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    ic = _spearman(pred, y) if len(y) > 2 else None
    hit_rate = float(np.mean((pred > 0) == (y > 0)))
    return {"rmse": rmse, "mae": mae, "spearman_ic": ic, "direction_hit_rate": hit_rate}


def _quality_direction(y: np.ndarray, pred: np.ndarray, prob: np.ndarray) -> dict[str, Any]:
    hit_rate = float(np.mean(pred == y))
    positive_rate = float(np.mean(y == 1))
    probability_ic = _spearman(prob, y) if len(y) > 2 else None
    return {"direction_hit_rate": hit_rate, "actual_positive_rate": positive_rate, "probability_spearman_ic": probability_ic}


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    ranks_a = pd.Series(a).rank(method="average").to_numpy(dtype=float)
    ranks_b = pd.Series(b).rank(method="average").to_numpy(dtype=float)
    if np.std(ranks_a) == 0.0 or np.std(ranks_b) == 0.0:
        return None
    return float(np.corrcoef(ranks_a, ranks_b)[0, 1])


def _feature_importance_rows(model_name: str, coefficients: np.ndarray) -> list[dict[str, Any]]:
    weights = np.abs(coefficients[1:])
    total = float(weights.sum())
    if total == 0.0:
        importances = np.zeros_like(weights)
    else:
        importances = weights / total
    rows = []
    for feature, importance, coefficient in zip(FEATURE_COLUMNS, importances, coefficients[1:]):
        rows.append(
            {
                "feature": feature,
                "importance": float(importance),
                "coefficient": float(coefficient),
                "model": model_name,
                "status": "AVAILABLE",
            }
        )
    return sorted(rows, key=lambda row: abs(float(row["importance"])), reverse=True)


def _split_payload(frame: pd.DataFrame, split_idx: int) -> dict[str, Any]:
    train = frame.iloc[:split_idx]
    test = frame.iloc[split_idx:]
    return {
        "schema_version": "strategy_factory_train_test_split_v0",
        "status": "COMPLETED",
        "split_method": "chronological_no_shuffle",
        "shuffle": False,
        "train_start": str(train["date"].iloc[0].date()),
        "train_end": str(train["date"].iloc[-1].date()),
        "test_start": str(test["date"].iloc[0].date()),
        "test_end": str(test["date"].iloc[-1].date()),
        "train_count": int(len(train)),
        "test_count": int(len(test)),
        "generated_at": _now(),
    }


def _leakage_payload(frame: pd.DataFrame, split_idx: int) -> dict[str, Any]:
    target_after_features = bool((frame["target_date"] > frame["date"]).all())
    train_max = frame.iloc[:split_idx]["date"].max()
    test_min = frame.iloc[split_idx:]["date"].min()
    chronological = bool(train_max < test_min)
    return {
        "schema_version": "strategy_factory_leakage_check_v0",
        "status": "PASS" if target_after_features and chronological else "FAIL",
        "target_after_feature_date": target_after_features,
        "chronological_split": chronological,
        "shuffle_used": False,
        "feature_window_uses_only_current_and_prior_returns": True,
        "target_definition": "next_period_net_return and next_period_direction",
        "train_max_date": str(train_max.date()),
        "test_min_date": str(test_min.date()),
        "generated_at": _now(),
    }


def _try_sklearn_models(train_x: np.ndarray, test_x: np.ndarray, train_y: np.ndarray, test_y: np.ndarray) -> list[dict[str, Any]]:
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    except Exception as exc:
        return [
            {"model": "random_forest_regressor", "status": "BLOCKED", "reason": f"sklearn unavailable: {exc}"},
            {"model": "gradient_boosting_regressor", "status": "BLOCKED", "reason": f"sklearn unavailable: {exc}"},
        ]
    rows = []
    for name, model in (
        ("random_forest_regressor", RandomForestRegressor(n_estimators=50, random_state=7, min_samples_leaf=5)),
        ("gradient_boosting_regressor", GradientBoostingRegressor(random_state=7)),
    ):
        model.fit(train_x, train_y)
        pred = model.predict(test_x)
        rows.append({"model": name, "status": "COMPLETED", "target": "next_period_net_return", "prediction_quality": _quality_regression(test_y, pred)})
    return rows


def run_current_run_ml_diagnostics(run_dir: Path, artifacts: dict[str, str], backtest: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    daily_path = Path(artifacts["daily_returns"])
    if not daily_path.is_file():
        return _blocked_payload("daily_returns.csv is missing; ML diagnostics require current-run returns.", artifacts)
    try:
        frame = _build_feature_frame(daily_path)
    except Exception as exc:
        return _blocked_payload(str(exc), artifacts)
    if len(frame) < 120:
        return _blocked_payload(f"Only {len(frame)} ML samples available after feature construction; at least 120 required.", artifacts)

    split_idx = max(80, int(len(frame) * 0.70))
    if split_idx >= len(frame) - 20:
        return _blocked_payload("Chronological split would leave too few test samples.", artifacts)

    train = frame.iloc[:split_idx]
    test = frame.iloc[split_idx:]
    train_x_raw = train[FEATURE_COLUMNS].to_numpy(dtype=float)
    test_x_raw = test[FEATURE_COLUMNS].to_numpy(dtype=float)
    train_x, test_x, _, _ = _standardize(train_x_raw, test_x_raw)
    train_y = train["target_next_return"].to_numpy(dtype=float)
    test_y = test["target_next_return"].to_numpy(dtype=float)
    train_direction = train["target_next_direction"].to_numpy(dtype=float)
    test_direction = test["target_next_direction"].to_numpy(dtype=int)

    linear_coef = _ols_fit(train_x, train_y)
    linear_pred = _predict_linear(linear_coef, test_x)
    ridge_coef = _ridge_fit(train_x, train_y, alpha=1.0)
    ridge_pred = _predict_linear(ridge_coef, test_x)
    logistic_coef = _logistic_fit(train_x, train_direction)
    logistic_prob, logistic_pred = _predict_logistic(logistic_coef, test_x)

    models = [
        {
            "model": "linear_regression_numpy",
            "status": "COMPLETED",
            "target": "next_period_net_return",
            "prediction_quality": _quality_regression(test_y, linear_pred),
        },
        {
            "model": "ridge_regression_numpy",
            "status": "COMPLETED",
            "target": "next_period_net_return",
            "prediction_quality": _quality_regression(test_y, ridge_pred),
        },
        {
            "model": "logistic_regression_numpy",
            "status": "COMPLETED",
            "target": "next_period_direction",
            "prediction_quality": _quality_direction(test_direction, logistic_pred, logistic_prob),
        },
    ]
    models.extend(_try_sklearn_models(train_x, test_x, train_y, test_y))

    importance = _feature_importance_rows("ridge_regression_numpy", ridge_coef)
    prediction_quality = {
        "schema_version": "strategy_factory_prediction_quality_v0",
        "status": "COMPLETED",
        "primary_model": "ridge_regression_numpy",
        "target_definition": "next_period_net_return",
        "models": models,
        "generated_at": _now(),
    }
    split = _split_payload(frame, split_idx)
    leakage = _leakage_payload(frame, split_idx)
    primary_quality = models[1]["prediction_quality"]
    recommendation = recommendation_from_evidence(metrics, primary_quality, models[2]["prediction_quality"])
    ml = {
        "schema_version": "strategy_factory_ml_diagnostics_run_v0",
        "status": "COMPLETED",
        "model": "ridge_regression_numpy",
        "models": models,
        "features_used": FEATURE_COLUMNS,
        "target_definition": "next_period_net_return; direction model uses next_period_direction",
        "sample_count": int(len(frame)),
        "train_count": split["train_count"],
        "test_count": split["test_count"],
        "train_dates": {"start": split["train_start"], "end": split["train_end"]},
        "test_dates": {"start": split["test_start"], "end": split["test_end"]},
        "prediction_quality": primary_quality,
        "direction_quality": models[2]["prediction_quality"],
        "feature_importance_available": True,
        "feature_importance": importance,
        "leakage_check": leakage,
        "recommendation": recommendation,
        "generated_at": _now(),
        "artifacts": artifacts,
    }

    _write_json(Path(artifacts["ml_diagnostics_run"]), ml)
    _write_json(Path(artifacts["prediction_quality"]), prediction_quality)
    _write_json(Path(artifacts["train_test_split"]), split)
    _write_json(Path(artifacts["leakage_check"]), leakage)
    _write_json(Path(artifacts["feature_importance_json"]), {"status": "COMPLETED", "model": "ridge_regression_numpy", "feature_importance": importance})
    _write_csv(Path(artifacts["feature_importance_csv"]), ["feature", "importance", "coefficient", "model", "status"], importance)
    return ml


def recommendation_from_evidence(metrics: dict[str, Any], regression_quality: dict[str, Any], direction_quality: dict[str, Any]) -> str:
    sharpe = _float(metrics.get("sharpe"))
    max_drawdown = _float(metrics.get("max_drawdown"))
    ic = _float(regression_quality.get("spearman_ic"))
    hit_rate = _float(direction_quality.get("direction_hit_rate"))
    if sharpe is not None and sharpe >= 1.0 and (ic is None or ic > 0.02) and (hit_rate is None or hit_rate >= 0.53):
        return "Candidate"
    if sharpe is not None and sharpe < 0.5:
        return "Watch" if (ic is not None and ic > 0.0) or (hit_rate is not None and hit_rate >= 0.50) else "Modify"
    if max_drawdown is not None and max_drawdown < -0.25:
        return "Modify"
    return "Watch"


def summarize_profit_loss_periods(daily_returns_path: Path, limit: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily = pd.read_csv(daily_returns_path)
    daily["date"] = pd.to_datetime(daily["date"])
    daily["net_return"] = pd.to_numeric(daily["net_return"], errors="coerce")
    daily = daily.dropna(subset=["date", "net_return"])
    if daily.empty:
        return [], []
    daily["month"] = daily["date"].dt.strftime("%Y-%m")
    monthly = daily.groupby("month")["net_return"].apply(lambda values: float((1.0 + values).prod() - 1.0)).reset_index()
    best = monthly.sort_values("net_return", ascending=False).head(limit).to_dict("records")
    worst = monthly.sort_values("net_return", ascending=True).head(limit).to_dict("records")
    return best, worst


def write_evidence_report(
    path: Path,
    run_manifest: dict[str, Any],
    artifacts: dict[str, str],
    backtest: dict[str, Any],
    metrics: dict[str, Any],
    ml: dict[str, Any],
) -> None:
    availability = _read_json(Path(artifacts.get("data_availability", "")), {})
    split = _read_json(Path(artifacts.get("train_test_split", "")), {})
    leakage = _read_json(Path(artifacts.get("leakage_check", "")), {})
    best, worst = summarize_profit_loss_periods(Path(artifacts["daily_returns"])) if Path(artifacts["daily_returns"]).is_file() else ([], [])
    recommendation = ml.get("recommendation") or "Watch"
    feature_rows = ml.get("feature_importance") or []
    selected = ", ".join(run_manifest.get("selected_material_names", [])) or "Unavailable"

    def fmt(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.6f}"
        return str(value)

    lines = [
        f"# Strategy Factory Evidence Report - {run_manifest.get('run_id')}",
        "",
        f"Recommendation: {recommendation}",
        "",
        "## Selected Materials",
        selected,
        "",
        "## Strategy Thesis",
        "Current Run Copper Momentum Volatility Filter V0 uses local copper ETF proxies and a DBC benchmark as prototype-only research evidence.",
        "",
        "## Proxy / Data Used",
        f"- Provider: {backtest.get('source_provider', 'Unavailable')}",
        f"- Testability decision: {backtest.get('testability_decision', availability.get('decision', 'Unavailable'))}",
        f"- Proxy symbols: {', '.join(availability.get('usable_symbols') or []) or backtest.get('universe', 'Unavailable')}",
        f"- Benchmark: {backtest.get('benchmark', metrics.get('benchmark', 'Unavailable'))}",
        "- Data limitations: prototype-only, not point-in-time clean, not survivorship-bias-free.",
        "",
        "## Backtest Methodology",
        "Monthly copper proxy momentum / volatility filter with 5 bps one-way turnover cost. Signals use historical proxy prices only and generate a research-only prototype return stream.",
        "",
        "## Metrics",
        *[f"- {key}: {fmt(value)}" for key, value in metrics.items() if key != "schema_version"],
        "",
        "## Charts",
        f"- Equity curve SVG: {artifacts.get('equity_curve_svg')}",
        f"- Drawdown SVG: {artifacts.get('drawdown_svg')}",
        "",
        "## ML Diagnostics",
        f"- Status: {ml.get('status')}",
        f"- Model used: {ml.get('model', 'Unavailable')}",
        f"- Target definition: {ml.get('target_definition', 'Unavailable')}",
        f"- Train dates: {split.get('train_start', 'Unavailable')} to {split.get('train_end', 'Unavailable')}",
        f"- Test dates: {split.get('test_start', 'Unavailable')} to {split.get('test_end', 'Unavailable')}",
        f"- Sample count: {ml.get('sample_count', 'Unavailable')}",
        f"- Prediction quality: {json.dumps(ml.get('prediction_quality', {}), sort_keys=True)}",
        f"- Direction quality: {json.dumps(ml.get('direction_quality', {}), sort_keys=True)}",
        f"- Leakage check: {leakage.get('status', 'Unavailable')}",
        "",
        "## Feature Importance",
        *[f"- {row.get('feature')}: {fmt(row.get('importance'))}" for row in feature_rows],
        "",
        "## Where It Made Money",
        *[f"- {row['month']}: {row['net_return']:.4%}" for row in best],
        "",
        "## Where It Lost Money",
        *[f"- {row['month']}: {row['net_return']:.4%}" for row in worst],
        "",
        "## Limitations",
        "- Public fallback data is provisional and unsuitable for admission claims.",
        "- ML uses a chronological split but remains diagnostic only; it is not an alpha proof.",
        "- Random forest and gradient boosting are marked blocked when sklearn is unavailable.",
        "- This report does not change strategy definitions, accounting logic, Combined/N semantics, paper ledger state, or live trading state.",
        "",
        "## Recommendation",
        recommendation,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
