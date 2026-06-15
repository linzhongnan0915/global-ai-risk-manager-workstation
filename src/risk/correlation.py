"""Strategy correlation diagnostics."""

from __future__ import annotations

from typing import Any

import pandas as pd


def strategy_correlation_report(
    strategy_returns: dict[str, list[float]],
    strategy_names: dict[str, str],
    max_pairwise_correlation: float = 0.75,
) -> dict[str, Any]:
    if not strategy_returns:
        return {"matrix": [], "pairs": [], "summary": {}}

    lengths = {len(values) for values in strategy_returns.values() if values}
    if not lengths:
        return {"matrix": [], "pairs": [], "summary": {}}
    if len(lengths) != 1:
        raise ValueError(
            "strategy_returns must already share a common dated window; "
            f"received lengths {sorted(lengths)}"
        )
    aligned = {
        strategy_id: [float(value) for value in values]
        for strategy_id, values in strategy_returns.items()
        if values
    }
    frame = pd.DataFrame(aligned).dropna(how="any")
    if frame.shape[0] < 2:
        return {"matrix": [], "pairs": [], "summary": {}}
    corr = frame.corr()
    corr = corr.fillna(0.0)
    matrix = []
    for row_id in corr.index:
        matrix.append(
            {
                "strategy_id": row_id,
                "name": strategy_names.get(row_id, row_id),
                "values": [
                    {
                        "strategy_id": col_id,
                        "name": strategy_names.get(col_id, col_id),
                        "correlation": float(corr.loc[row_id, col_id]),
                        "status": _correlation_status(float(corr.loc[row_id, col_id]), max_pairwise_correlation, row_id == col_id),
                    }
                    for col_id in corr.columns
                ],
            }
        )

    pairs = []
    ids = list(corr.columns)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            value = float(corr.loc[left, right])
            pairs.append(
                {
                    "left_strategy_id": left,
                    "left_name": strategy_names.get(left, left),
                    "right_strategy_id": right,
                    "right_name": strategy_names.get(right, right),
                    "correlation": value,
                    "status": _correlation_status(value, max_pairwise_correlation, False),
                    "limit": max_pairwise_correlation,
                }
            )
    pairs.sort(key=lambda row: abs(row["correlation"]), reverse=True)
    duplicate_breaches = [row for row in pairs if row["correlation"] >= max_pairwise_correlation]
    hedge_relationships = [row for row in pairs if row["correlation"] <= -max_pairwise_correlation]
    by_strategy = _strategy_duplicate_exposure_map(duplicate_breaches)
    positive_pairs = sorted(pairs, key=lambda row: row["correlation"], reverse=True)
    average_abs = sum(abs(row["correlation"]) for row in pairs) / len(pairs) if pairs else 0.0
    return {
        "matrix": matrix,
        "pairs": pairs,
        "duplicate_exposure_by_strategy": by_strategy,
        "summary": {
            "strategy_count": len(ids),
            "pair_count": len(pairs),
            "average_abs_correlation": float(average_abs),
            "max_abs_correlation": float(abs(pairs[0]["correlation"])) if pairs else 0.0,
            "max_pair": pairs[0] if pairs else None,
            "breach_count": len(duplicate_breaches),
            "breaches": duplicate_breaches[:20],
            "hedge_relationship_count": len(hedge_relationships),
            "hedge_relationships": hedge_relationships[:20],
            "max_positive_pair": positive_pairs[0] if positive_pairs else None,
            "limit": max_pairwise_correlation,
            "interpretation": (
                "Independent strategies should have distinct return drivers. "
                "High positive correlation can indicate duplicate exposure. Strong negative correlation is treated as a hedge relationship that requires stability review, not as a duplicate-exposure breach."
            ),
        },
    }


def _correlation_status(value: float, limit: float, diagonal: bool) -> str:
    if diagonal:
        return "self"
    if value >= limit:
        return "breach"
    if value <= -limit:
        return "hedge_review"
    abs_value = abs(value)
    if abs_value >= limit * 0.8:
        return "warning"
    if abs_value >= limit * 0.6:
        return "watch"
    return "ok"


def _strategy_duplicate_exposure_map(breaches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in breaches:
        for side, other_side in [("left", "right"), ("right", "left")]:
            strategy_id = row[f"{side}_strategy_id"]
            other_id = row[f"{other_side}_strategy_id"]
            output.setdefault(
                strategy_id,
                {
                    "breach_count": 0,
                    "max_abs_correlation": 0.0,
                    "highest_overlap": None,
                    "allocation_blocker": True,
                    "reason_code": "duplicate_exposure",
                    "interpretation": "Strategy has excessive correlation to another strategy and should not be treated as independent allocation.",
                },
            )
            output[strategy_id]["breach_count"] += 1
            abs_corr = abs(row["correlation"])
            if abs_corr > output[strategy_id]["max_abs_correlation"]:
                output[strategy_id]["max_abs_correlation"] = abs_corr
                output[strategy_id]["highest_overlap"] = {
                    "strategy_id": other_id,
                    "name": row[f"{other_side}_name"],
                    "correlation": row["correlation"],
                }
    return output
