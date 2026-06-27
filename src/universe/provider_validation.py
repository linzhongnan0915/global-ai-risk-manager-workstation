"""Validation helpers for staged universe provider files."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.universe.security_master import normalize_ticker

SAMPLE_TEMPLATE_LABEL = "SAMPLE_TEMPLATE_ONLY"


@dataclass(frozen=True)
class ProviderTableSpec:
    stem: str
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    numeric_columns: tuple[str, ...] = ()
    non_negative_columns: tuple[str, ...] = ()
    boolean_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderValidationIssue:
    severity: str
    table: str
    message: str
    row_number: int | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_warning(self) -> str:
        location = self.table
        if self.row_number is not None:
            location += f" row {self.row_number}"
        if self.field:
            location += f" field {self.field}"
        return f"{location}: {self.message}"


@dataclass(frozen=True)
class LoadedProviderTable:
    name: str
    path: str
    frame: pd.DataFrame


@dataclass(frozen=True)
class ValidatedProviderTable:
    name: str
    path: str
    frame: pd.DataFrame
    rejected_rows: int
    issues: list[ProviderValidationIssue]

    def metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "valid_rows": int(len(self.frame)),
            "rejected_rows": int(self.rejected_rows),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class ProviderValidationError(ValueError):
    """Raised when a provider file violates the table contract."""


SECURITY_MASTER_SPEC = ProviderTableSpec(
    stem="security_master",
    required_columns=(
        "security_id",
        "ticker",
        "company_name",
        "exchange",
        "asset_type",
        "country",
        "currency",
        "is_active",
        "data_source",
        "last_updated",
    ),
    optional_columns=(
        "sector",
        "industry",
        "market_cap",
        "price",
        "adv_20d",
        "adv_60d",
        "shares_outstanding",
        "ipo_date",
        "delisting_date",
        "is_common_stock",
        "is_adr",
        "is_etf",
        "is_reit",
        "is_preferred",
        "is_warrant",
        "is_unit",
        "is_closed_end_fund",
        "is_spac_shell",
    ),
    numeric_columns=("market_cap", "price", "adv_20d", "adv_60d", "shares_outstanding"),
    non_negative_columns=("market_cap", "price", "adv_20d", "adv_60d", "shares_outstanding"),
    boolean_columns=(
        "is_active",
        "is_common_stock",
        "is_adr",
        "is_etf",
        "is_reit",
        "is_preferred",
        "is_warrant",
        "is_unit",
        "is_closed_end_fund",
        "is_spac_shell",
    ),
    date_columns=("last_updated", "ipo_date", "delisting_date"),
)

INDEX_MEMBERSHIP_SPEC = ProviderTableSpec(
    stem="index_membership",
    required_columns=(
        "security_id",
        "ticker",
        "index_name",
        "membership_start_date",
        "as_of_date",
        "data_source",
        "last_updated",
    ),
    optional_columns=("membership_end_date", "membership_status", "weight"),
    numeric_columns=("weight",),
    non_negative_columns=("weight",),
    date_columns=("membership_start_date", "membership_end_date", "as_of_date", "last_updated"),
)

PRICE_VOLUME_SNAPSHOT_SPEC = ProviderTableSpec(
    stem="prices_volume_snapshot",
    required_columns=(
        "security_id",
        "ticker",
        "as_of_date",
        "price",
        "adv_20d",
        "adv_60d",
        "market_cap",
        "data_source",
        "last_updated",
    ),
    optional_columns=("currency", "close", "volume", "shares_outstanding"),
    numeric_columns=("price", "adv_20d", "adv_60d", "market_cap", "close", "volume", "shares_outstanding"),
    non_negative_columns=("price", "adv_20d", "adv_60d", "market_cap", "close", "volume", "shares_outstanding"),
    date_columns=("as_of_date", "last_updated"),
)

SECTOR_INDUSTRY_SPEC = ProviderTableSpec(
    stem="sector_industry",
    required_columns=("security_id", "ticker", "sector", "industry", "data_source", "last_updated"),
    optional_columns=("classification_system",),
    date_columns=("last_updated",),
)

ALL_PROVIDER_SPECS = (
    SECURITY_MASTER_SPEC,
    INDEX_MEMBERSHIP_SPEC,
    PRICE_VOLUME_SNAPSHOT_SPEC,
    SECTOR_INDUSTRY_SPEC,
)


def load_and_validate_provider_table(
    input_dir: str | Path,
    spec: ProviderTableSpec,
    *,
    allow_parquet: bool = True,
) -> ValidatedProviderTable | None:
    loaded = load_provider_table(input_dir, spec, allow_parquet=allow_parquet)
    if loaded is None:
        return None
    clean, issues = validate_provider_frame(loaded.frame, spec)
    return ValidatedProviderTable(
        name=loaded.name,
        path=loaded.path,
        frame=clean,
        rejected_rows=int(len(loaded.frame) - len(clean)),
        issues=issues,
    )


def load_provider_table(
    input_dir: str | Path,
    spec: ProviderTableSpec,
    *,
    allow_parquet: bool = True,
) -> LoadedProviderTable | None:
    directory = Path(input_dir)
    csv_path = directory / f"{spec.stem}.csv"
    parquet_path = directory / f"{spec.stem}.parquet"
    if csv_path.exists():
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        path = csv_path
    elif allow_parquet and parquet_path.exists():
        frame = pd.read_parquet(parquet_path)
        path = parquet_path
    else:
        return None
    frame = normalize_provider_columns(frame, spec.stem)
    validate_required_columns(frame, spec)
    return LoadedProviderTable(name=spec.stem, path=str(path), frame=frame)


def normalize_provider_columns(frame: pd.DataFrame, table_name: str) -> pd.DataFrame:
    renamed: dict[str, str] = {}
    seen: set[str] = set()
    for column in frame.columns:
        normalized = re.sub(r"\s+", "_", str(column).strip().lower())
        if normalized in seen:
            raise ProviderValidationError(f"{table_name} has duplicate column after normalization: {normalized}")
        seen.add(normalized)
        renamed[str(column)] = normalized
    return frame.rename(columns=renamed)


def validate_required_columns(frame: pd.DataFrame, spec: ProviderTableSpec) -> None:
    missing = sorted(set(spec.required_columns) - set(frame.columns))
    if missing:
        raise ProviderValidationError(f"{spec.stem} missing required columns: {missing}")


def validate_provider_frame(
    frame: pd.DataFrame,
    spec: ProviderTableSpec,
) -> tuple[pd.DataFrame, list[ProviderValidationIssue]]:
    working = frame.copy().astype(object)
    issues: list[ProviderValidationIssue] = []
    invalid_indexes: set[int] = set()

    for index, row in working.iterrows():
        row_number = int(index) + 2
        if _is_sample_template_row(row):
            invalid_indexes.add(index)
            issues.append(
                ProviderValidationIssue(
                    severity="warning",
                    table=spec.stem,
                    row_number=row_number,
                    message=f"{SAMPLE_TEMPLATE_LABEL} rows are templates and cannot populate production artifacts",
                )
            )
            continue

        for column in spec.required_columns:
            if _is_blank(row.get(column)):
                invalid_indexes.add(index)
                issues.append(
                    ProviderValidationIssue(
                        severity="warning",
                        table=spec.stem,
                        row_number=row_number,
                        field=column,
                        message="required field is missing",
                    )
                )

        if "ticker" in working.columns and not _is_blank(row.get("ticker")):
            working.at[index, "ticker"] = normalize_ticker(str(row.get("ticker")))

        if "security_id" in working.columns and not _is_blank(row.get("security_id")):
            working.at[index, "security_id"] = str(row.get("security_id")).strip()

        for column in spec.numeric_columns:
            if column not in working.columns:
                continue
            value = row.get(column)
            if _is_blank(value):
                working.at[index, column] = None
                if column in spec.required_columns:
                    invalid_indexes.add(index)
                    issues.append(
                        ProviderValidationIssue(
                            severity="warning",
                            table=spec.stem,
                            row_number=row_number,
                            field=column,
                            message="required numeric field is missing",
                        )
                    )
                continue
            parsed = _parse_float(value)
            if parsed is None:
                invalid_indexes.add(index)
                issues.append(
                    ProviderValidationIssue(
                        severity="warning",
                        table=spec.stem,
                        row_number=row_number,
                        field=column,
                        message=f"invalid numeric value: {value}",
                    )
                )
                continue
            if column in spec.non_negative_columns and parsed < 0:
                invalid_indexes.add(index)
                issues.append(
                    ProviderValidationIssue(
                        severity="warning",
                        table=spec.stem,
                        row_number=row_number,
                        field=column,
                        message=f"negative numeric value is not allowed: {value}",
                    )
                )
                continue
            working.at[index, column] = parsed

        for column in spec.boolean_columns:
            if column not in working.columns:
                continue
            value = row.get(column)
            if _is_blank(value):
                working.at[index, column] = None
                if column in spec.required_columns:
                    invalid_indexes.add(index)
                    issues.append(
                        ProviderValidationIssue(
                            severity="warning",
                            table=spec.stem,
                            row_number=row_number,
                            field=column,
                            message="required boolean field is missing",
                        )
                    )
                continue
            parsed_bool = _parse_bool(value)
            if parsed_bool is None:
                invalid_indexes.add(index)
                issues.append(
                    ProviderValidationIssue(
                        severity="warning",
                        table=spec.stem,
                        row_number=row_number,
                        field=column,
                        message=f"invalid boolean value: {value}",
                    )
                )
                continue
            working.at[index, column] = parsed_bool

        for column in spec.date_columns:
            if column not in working.columns:
                continue
            value = row.get(column)
            if _is_blank(value):
                working.at[index, column] = None
                if column in spec.required_columns:
                    invalid_indexes.add(index)
                    issues.append(
                        ProviderValidationIssue(
                            severity="warning",
                            table=spec.stem,
                            row_number=row_number,
                            field=column,
                            message="required date field is missing",
                        )
                    )
                continue
            parsed_date = _parse_date(value)
            if parsed_date is None:
                invalid_indexes.add(index)
                issues.append(
                    ProviderValidationIssue(
                        severity="warning",
                        table=spec.stem,
                        row_number=row_number,
                        field=column,
                        message=f"invalid date value: {value}",
                    )
                )
                continue
            working.at[index, column] = parsed_date

    valid = working.drop(index=list(invalid_indexes), errors="ignore").reset_index(drop=True)
    return valid, issues


def validation_warnings(issues: list[ProviderValidationIssue]) -> list[str]:
    return [issue.to_warning() for issue in issues]


def table_metadata(table: ValidatedProviderTable | None) -> dict[str, Any] | None:
    if table is None:
        return None
    return table.metadata()


def _is_sample_template_row(row: pd.Series) -> bool:
    source_columns = [column for column in ("data_source", "source", "source_status") if column in row.index]
    return any(str(row.get(column) or "").strip().upper() == SAMPLE_TEMPLATE_LABEL for column in source_columns)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip() == ""


def _parse_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "active"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "inactive"}:
        return False
    return None


def _parse_date(value: Any) -> str | None:
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()
