"""Security master helpers for the universe foundation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from src.universe.models import SecurityMasterRecord


def normalize_ticker(ticker: str) -> str:
    return str(ticker).strip().upper()


def records_to_dataframe(records: Iterable[SecurityMasterRecord]) -> pd.DataFrame:
    return pd.DataFrame([record.to_dict() for record in records])


def records_from_dataframe(frame: pd.DataFrame) -> list[SecurityMasterRecord]:
    return [SecurityMasterRecord.from_dict(row) for row in frame.to_dict(orient="records")]


def load_security_master_csv(path: str | Path) -> list[SecurityMasterRecord]:
    return records_from_dataframe(pd.read_csv(path))


def dedupe_security_master(records: Iterable[SecurityMasterRecord]) -> list[SecurityMasterRecord]:
    by_ticker: dict[str, SecurityMasterRecord] = {}
    for record in records:
        ticker = normalize_ticker(record.ticker)
        previous = by_ticker.get(ticker)
        if previous is None:
            by_ticker[ticker] = record
            continue
        by_ticker[ticker] = _prefer_record(previous, record)
    return [by_ticker[ticker] for ticker in sorted(by_ticker)]


def write_security_master(frame: pd.DataFrame, output_dir: str | Path) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "security_master.csv"
    parquet_path = output / "security_master.parquet"
    frame.to_csv(csv_path, index=False)
    parquet_written = _try_write_parquet(frame, parquet_path)
    return {
        "csv_path": str(csv_path),
        "parquet_path": str(parquet_path) if parquet_written else None,
        "parquet_written": parquet_written,
    }


def _prefer_record(left: SecurityMasterRecord, right: SecurityMasterRecord) -> SecurityMasterRecord:
    left_score = _record_score(left)
    right_score = _record_score(right)
    return right if right_score > left_score else left


def _record_score(record: SecurityMasterRecord) -> int:
    fields = [
        record.company_name,
        record.exchange,
        record.asset_type,
        record.sector,
        record.industry,
        record.market_cap,
        record.price,
        record.adv_20d,
        record.adv_60d,
        record.last_updated,
    ]
    return sum(1 for value in fields if value not in {None, ""})


def _try_write_parquet(frame: pd.DataFrame, path: Path) -> bool:
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        return False
    return True
