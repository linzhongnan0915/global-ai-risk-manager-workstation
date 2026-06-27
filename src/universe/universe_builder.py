"""Build versioned universe snapshots from provider candidates and config filters."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.universe.models import SecurityMasterRecord, UniverseMembershipRecord, UniverseSnapshot
from src.universe.providers import UniverseDataProvider, default_universe_provider
from src.universe.quality_report import build_quality_report
from src.universe.security_master import records_to_dataframe, write_security_master
from src.universe.universe_definitions import DEFAULT_DEFINITIONS_PATH, UniverseDefinition, load_universe_config
from src.universe.universe_filters import FilterDecision, apply_universe_filters

DEFAULT_UNIVERSE_OUTPUT_DIR = Path("data/universe")
POINT_IN_TIME_STATUS = "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"
RESEARCH_USE = "PROTOTYPE_ONLY"
NOT_SURVIVOR_BIAS_FREE = True


@dataclass(frozen=True)
class UniverseBuildResult:
    snapshot_payload: dict[str, Any]
    quality_report: dict[str, Any]
    security_master_rows: int
    membership_rows: int
    output_paths: dict[str, str | None]


class UniverseBuilder:
    def __init__(
        self,
        *,
        root: str | Path = ".",
        definitions_path: str | Path | None = None,
        output_dir: str | Path | None = None,
        provider: UniverseDataProvider | None = None,
        universe_names: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.root = Path(root)
        self.definitions_path = Path(definitions_path) if definitions_path else self.root / DEFAULT_DEFINITIONS_PATH
        self.output_dir = Path(output_dir) if output_dir else self.root / DEFAULT_UNIVERSE_OUTPUT_DIR
        self.provider = provider or default_universe_provider(self.root)
        self.universe_names = tuple(universe_names) if universe_names else None

    def build(self, *, as_of_date: str | None = None) -> UniverseBuildResult:
        as_of = as_of_date or date.today().isoformat()
        generated_at = datetime.now(timezone.utc).isoformat()
        config = load_universe_config(self.definitions_path)
        settings = config.global_settings
        definitions = self._selected_definitions(config.definitions)
        stale_days = int(settings.get("stale_data_threshold_days", 5))
        provider_result = self.provider.fetch_security_master_candidates(as_of_date=as_of)
        records = provider_result.records
        version = f"universe_foundation_v1_{as_of.replace('-', '')}"

        security_master = records_to_dataframe(records)
        master_status = write_security_master(security_master, self.output_dir)

        snapshots: dict[str, UniverseSnapshot] = {}
        membership_records: list[UniverseMembershipRecord] = []
        excluded_rows: list[dict[str, Any]] = []
        for definition in definitions:
            candidate_records = _records_for_universe(records, definition.name, provider_result.metadata)
            snapshot, members, exclusions = self._build_one_universe(
                candidate_records,
                definition,
                as_of_date=as_of,
                generated_at=generated_at,
                version=version,
                provider_source=provider_result.source,
                provider_warnings=provider_result.warnings,
                stale_data_threshold_days=stale_days,
                max_universe_size=int(settings.get("max_universe_size", 5000)),
            )
            snapshots[definition.name] = snapshot
            membership_records.extend(members)
            excluded_rows.extend(exclusions)

        membership_frame = pd.DataFrame([record.to_dict() for record in membership_records])
        if membership_frame.empty:
            membership_frame = pd.DataFrame(columns=list(UniverseMembershipRecord.__dataclass_fields__))
        membership_paths = self._write_membership(membership_frame)

        snapshot_payload = {
            "schema_version": "universe_snapshot_bundle_v1",
            "as_of_date": as_of,
            "generated_at": generated_at,
            "version": version,
            "point_in_time_status": POINT_IN_TIME_STATUS,
            "research_use": settings.get("research_use") or RESEARCH_USE,
            "not_survivor_bias_free": bool(settings.get("not_survivor_bias_free", NOT_SURVIVOR_BIAS_FREE)),
            "label_contract": {
                "DATA_SOURCE": provider_result.source,
                "POINT_IN_TIME_STATUS": POINT_IN_TIME_STATUS,
                "RESEARCH_USE": settings.get("research_use") or RESEARCH_USE,
                "NOT_SURVIVOR_BIAS_FREE": bool(settings.get("not_survivor_bias_free", NOT_SURVIVOR_BIAS_FREE)),
            },
            "source_status": provider_result.status,
            "data_source": provider_result.source,
            "provider": provider_result.to_dict(),
            "global_settings": settings,
            "universes": {name: snapshot.to_dict() for name, snapshot in snapshots.items()},
            "exclusions": excluded_rows,
        }
        snapshot_path = self.output_dir / "current_universe_snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot_payload, indent=2), encoding="utf-8")

        quality_report = build_quality_report(
            snapshots,
            provider_status=provider_result.to_dict(),
            parquet_status={
                "security_master_parquet_written": bool(master_status["parquet_written"]),
                "membership_parquet_written": bool(membership_paths["parquet_written"]),
                "fallback": "CSV_JSON_ONLY" if not master_status["parquet_written"] or not membership_paths["parquet_written"] else None,
            },
        )
        quality_path = self.output_dir / "universe_quality_report.json"
        quality_path.write_text(json.dumps(quality_report, indent=2), encoding="utf-8")
        self._append_refresh_log(
            {
                "generated_at": generated_at,
                "as_of_date": as_of,
                "version": version,
                "provider_status": provider_result.status,
                "security_master_rows": len(security_master),
                "membership_rows": len(membership_frame),
                "snapshot_path": str(snapshot_path),
                "quality_path": str(quality_path),
            }
        )
        return UniverseBuildResult(
            snapshot_payload=snapshot_payload,
            quality_report=quality_report,
            security_master_rows=len(security_master),
            membership_rows=len(membership_frame),
            output_paths={
                "security_master_csv": str(self.output_dir / "security_master.csv"),
                "security_master_parquet": master_status["parquet_path"],
                "universe_membership_csv": str(self.output_dir / "universe_membership.csv"),
                "universe_membership_parquet": membership_paths["parquet_path"],
                "current_universe_snapshot_json": str(snapshot_path),
                "universe_quality_report_json": str(quality_path),
                "universe_refresh_log_jsonl": str(self.output_dir / "universe_refresh_log.jsonl"),
            },
        )

    def _selected_definitions(self, definitions: dict[str, UniverseDefinition]) -> list[UniverseDefinition]:
        if self.universe_names is None:
            return list(definitions.values())
        unknown = [name for name in self.universe_names if name not in definitions]
        if unknown:
            raise ValueError(f"unknown universe(s): {unknown}")
        return [definitions[name] for name in self.universe_names]

    def _build_one_universe(
        self,
        records: list[SecurityMasterRecord],
        definition: UniverseDefinition,
        *,
        as_of_date: str,
        generated_at: str,
        version: str,
        provider_source: str,
        provider_warnings: list[str],
        stale_data_threshold_days: int,
        max_universe_size: int,
    ) -> tuple[UniverseSnapshot, list[UniverseMembershipRecord], list[dict[str, Any]]]:
        decisions = apply_universe_filters(
            records,
            definition,
            as_of_date=as_of_date,
            stale_data_threshold_days=stale_data_threshold_days,
        )
        decisions = self._apply_max_size_cap(decisions, definition, max_universe_size)
        included = [record for record, decision in decisions if decision.included]
        excluded = [(record, decision) for record, decision in decisions if not decision.included]
        excluded_by_reason = Counter(decision.reason for _, decision in excluded)
        members = [
            UniverseMembershipRecord(
                universe_name=definition.name,
                security_id=record.security_id,
                ticker=record.ticker,
                membership_start_date=as_of_date,
                membership_end_date=None,
                as_of_date=as_of_date,
                source=provider_source,
                version=version,
                inclusion_reason="included_by_config_filters",
            )
            for record in included
        ]
        warning_set = set(provider_warnings)
        if not included:
            warning_set.add(f"{definition.name}: no included securities after configured gates.")
        if any(reason.startswith("missing_") for reason in excluded_by_reason):
            warning_set.add(f"{definition.name}: one or more required fields are missing for candidates.")
        warning_set.add("Point-in-time status is CURRENT_MEMBERSHIP_ONLY_PROVISIONAL until historical membership is supplied.")

        snapshot = UniverseSnapshot(
            universe_name=definition.name,
            as_of_date=as_of_date,
            version=version,
            total_candidates=len(records),
            included_count=len(included),
            excluded_count=len(excluded),
            included_tickers=sorted(record.ticker for record in included),
            excluded_by_reason=dict(sorted(excluded_by_reason.items())),
            sector_counts=_counts_by(included, "sector"),
            market_cap_summary=_numeric_summary([record.market_cap for record in included]),
            liquidity_summary=_numeric_summary([record.adv_20d for record in included], field_name="adv_20d"),
            data_quality_warnings=sorted(warning_set),
            data_source=provider_source,
            point_in_time_status=POINT_IN_TIME_STATUS,
            research_use=RESEARCH_USE,
            not_survivor_bias_free=NOT_SURVIVOR_BIAS_FREE,
            last_refresh_time=generated_at,
            coverage_summary=_coverage_summary(records),
            asset_type_distribution=_counts_by(records, "asset_type"),
            exchange_distribution=_counts_by(records, "exchange"),
        )
        exclusions = [
            {
                "universe_name": definition.name,
                "security_id": record.security_id,
                "ticker": record.ticker,
                "exclusion_reason": decision.reason,
                "as_of_date": as_of_date,
                "version": version,
            }
            for record, decision in excluded
        ]
        return snapshot, members, exclusions

    def _apply_max_size_cap(
        self,
        decisions: list[tuple[SecurityMasterRecord, FilterDecision]],
        definition: UniverseDefinition,
        max_universe_size: int,
    ) -> list[tuple[SecurityMasterRecord, FilterDecision]]:
        included = [record for record, decision in decisions if decision.included]
        if definition.name not in {"US_BROAD_MARKET", "US_ALL_COMMON_RESEARCH"} or len(included) <= max_universe_size:
            return decisions
        ranked = sorted(
            included,
            key=lambda record: (
                record.market_cap is not None,
                record.market_cap or 0,
                record.adv_60d is not None,
                record.adv_60d or 0,
                record.ticker,
            ),
            reverse=True,
        )
        keep = {record.security_id for record in ranked[:max_universe_size]}
        capped: list[tuple[SecurityMasterRecord, FilterDecision]] = []
        for record, decision in decisions:
            if decision.included and record.security_id not in keep:
                capped.append((record, FilterDecision(False, "max_universe_size_cap")))
            else:
                capped.append((record, decision))
        return capped

    def _write_membership(self, frame: pd.DataFrame) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / "universe_membership.csv"
        parquet_path = self.output_dir / "universe_membership.parquet"
        frame.to_csv(csv_path, index=False)
        parquet_written = _try_write_parquet(frame, parquet_path)
        return {
            "csv_path": str(csv_path),
            "parquet_path": str(parquet_path) if parquet_written else None,
            "parquet_written": parquet_written,
        }

    def _append_refresh_log(self, payload: dict[str, Any]) -> None:
        log_path = self.output_dir / "universe_refresh_log.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _counts_by(records: list[SecurityMasterRecord], field_name: str) -> dict[str, int]:
    counts = Counter(str(getattr(record, field_name) or "Unknown") for record in records)
    return dict(sorted(counts.items()))


def _records_for_universe(
    records: list[SecurityMasterRecord],
    universe_name: str,
    provider_metadata: dict[str, Any],
) -> list[SecurityMasterRecord]:
    tickers_by_universe = provider_metadata.get("universe_candidate_tickers") or {}
    if universe_name not in tickers_by_universe:
        return records
    allowed = {str(ticker).strip().upper() for ticker in tickers_by_universe.get(universe_name) or []}
    if not allowed:
        return []
    return [record for record in records if record.ticker in allowed]


def _coverage_summary(records: list[SecurityMasterRecord]) -> dict[str, Any]:
    total = len(records)
    counts = {
        "price": sum(record.price is not None for record in records),
        "adv_20d": sum(record.adv_20d is not None for record in records),
        "adv_60d": sum(record.adv_60d is not None for record in records),
        "market_cap": sum(record.market_cap is not None for record in records),
        "sector": sum(bool(record.sector) for record in records),
        "industry": sum(bool(record.industry) for record in records),
    }
    return {
        field: {"covered": count, "total": total, "ratio": float(count / total) if total else 0.0}
        for field, count in counts.items()
    }


def _numeric_summary(values: list[float | None], *, field_name: str = "market_cap") -> dict[str, float | int | None]:
    clean = pd.Series([value for value in values if value is not None], dtype="float64")
    if clean.empty:
        return {f"{field_name}_count": 0, "min": None, "median": None, "max": None}
    return {
        f"{field_name}_count": int(clean.count()),
        "min": float(clean.min()),
        "median": float(clean.median()),
        "max": float(clean.max()),
    }


def _try_write_parquet(frame: pd.DataFrame, path: Path) -> bool:
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        return False
    return True
