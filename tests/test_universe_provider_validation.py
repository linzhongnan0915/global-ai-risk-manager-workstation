from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.universe.provider_validation import (
    PRICE_VOLUME_SNAPSHOT_SPEC,
    SECURITY_MASTER_SPEC,
    ProviderValidationError,
    load_and_validate_provider_table,
    normalize_provider_columns,
    validate_provider_frame,
)


def test_missing_required_column_fails_with_clear_message(tmp_path: Path):
    input_dir = tmp_path / "provider"
    input_dir.mkdir()
    pd.DataFrame(
        [
            {
                "security_id": "SEC-A",
                "ticker": "AAA",
                "as_of_date": "2026-06-22",
                "price": "100",
                "adv_20d": "25000000",
                "market_cap": "100000000000",
                "data_source": "boss_file",
                "last_updated": "2026-06-22",
            }
        ]
    ).to_csv(input_dir / "prices_volume_snapshot.csv", index=False)

    with pytest.raises(ProviderValidationError, match="prices_volume_snapshot missing required columns"):
        load_and_validate_provider_table(input_dir, PRICE_VOLUME_SNAPSHOT_SPEC)


def test_bad_numeric_fields_are_rejected():
    frame = normalize_provider_columns(
        pd.DataFrame(
            [
                {
                    "security_id": "SEC-A",
                    "ticker": " aaa ",
                    "as_of_date": "2026-06-22",
                    "price": "100.25",
                    "adv_20d": "25000000",
                    "adv_60d": "21000000",
                    "market_cap": "100000000000",
                    "data_source": "boss_file",
                    "last_updated": "2026-06-22",
                },
                {
                    "security_id": "SEC-B",
                    "ticker": "BBB",
                    "as_of_date": "2026-06-22",
                    "price": "not-a-number",
                    "adv_20d": "7000000",
                    "adv_60d": "5000000",
                    "market_cap": "8000000000",
                    "data_source": "boss_file",
                    "last_updated": "2026-06-22",
                },
            ]
        ),
        PRICE_VOLUME_SNAPSHOT_SPEC.stem,
    )

    clean, issues = validate_provider_frame(frame, PRICE_VOLUME_SNAPSHOT_SPEC)

    assert clean["ticker"].tolist() == ["AAA"]
    assert any(issue.field == "price" and "invalid numeric" in issue.message for issue in issues)


def test_sample_template_rows_are_rejected():
    frame = normalize_provider_columns(
        pd.DataFrame(
            [
                {
                    "security_id": "SAMPLE-SEC-001",
                    "ticker": "SAMP_A",
                    "company_name": "Sample Template Alpha Corp",
                    "exchange": "NYSE",
                    "asset_type": "COMMON_STOCK",
                    "country": "US",
                    "currency": "USD",
                    "is_active": "true",
                    "data_source": "SAMPLE_TEMPLATE_ONLY",
                    "last_updated": "2026-06-22",
                }
            ]
        ),
        SECURITY_MASTER_SPEC.stem,
    )

    clean, issues = validate_provider_frame(frame, SECURITY_MASTER_SPEC)

    assert clean.empty
    assert any("templates" in issue.message for issue in issues)
