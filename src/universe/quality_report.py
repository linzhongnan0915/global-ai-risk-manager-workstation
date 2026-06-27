"""Quality reporting helpers for universe snapshots."""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.universe.models import UniverseSnapshot


def build_quality_report(
    snapshots: dict[str, UniverseSnapshot],
    *,
    provider_status: dict[str, Any],
    parquet_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings = []
    excluded = Counter()
    for snapshot in snapshots.values():
        warnings.extend(snapshot.data_quality_warnings)
        excluded.update(snapshot.excluded_by_reason)
    return {
        "schema_version": "universe_quality_report_v1",
        "provider_status": provider_status,
        "parquet_status": parquet_status or {},
        "point_in_time_status": "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL",
        "research_use": "PROTOTYPE_ONLY",
        "not_survivor_bias_free": True,
        "universe_count": len(snapshots),
        "total_included_by_universe": {
            name: snapshot.included_count for name, snapshot in snapshots.items()
        },
        "total_candidates_by_universe": {
            name: snapshot.total_candidates for name, snapshot in snapshots.items()
        },
        "excluded_by_reason_total": dict(sorted(excluded.items())),
        "warnings": sorted(set(warnings)),
        "provisional_data_warnings": [
            warning for warning in sorted(set(warnings))
            if "provisional" in warning.lower() or "current" in warning.lower() or "PIT" in warning
        ],
        "coverage_by_universe": {
            name: snapshot.coverage_summary for name, snapshot in snapshots.items()
        },
        "asset_type_distribution_by_universe": {
            name: snapshot.asset_type_distribution for name, snapshot in snapshots.items()
        },
        "exchange_distribution_by_universe": {
            name: snapshot.exchange_distribution for name, snapshot in snapshots.items()
        },
    }


def summarize_snapshot_for_api(snapshot: UniverseSnapshot) -> dict[str, Any]:
    return {
        "universe_name": snapshot.universe_name,
        "as_of_date": snapshot.as_of_date,
        "version": snapshot.version,
        "total_candidates": snapshot.total_candidates,
        "included_count": snapshot.included_count,
        "excluded_count": snapshot.excluded_count,
        "excluded_by_reason": snapshot.excluded_by_reason,
        "data_source": snapshot.data_source,
        "point_in_time_status": snapshot.point_in_time_status,
        "research_use": snapshot.research_use,
        "not_survivor_bias_free": snapshot.not_survivor_bias_free,
        "last_refresh_time": snapshot.last_refresh_time,
        "warnings": snapshot.data_quality_warnings,
        "sector_counts": snapshot.sector_counts,
        "market_cap_summary": snapshot.market_cap_summary,
        "liquidity_summary": snapshot.liquidity_summary,
        "coverage_summary": snapshot.coverage_summary,
        "asset_type_distribution": snapshot.asset_type_distribution,
        "exchange_distribution": snapshot.exchange_distribution,
    }
