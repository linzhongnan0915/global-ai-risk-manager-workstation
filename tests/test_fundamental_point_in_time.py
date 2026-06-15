from __future__ import annotations

import json

import pandas as pd

from src.strategies.fundamental_data import (
    SecEdgarClient,
    build_filing_event_panel,
    facts_as_of,
    normalize_company_facts,
)


def _company_facts() -> dict:
    return {
        "cik": 320193,
        "entityName": "Example Corp",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2023-12-31",
                                "val": 50,
                                "accn": "0001-24-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                }
            },
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 100,
                                "accn": "0001-24-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            },
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 110,
                                "accn": "0001-24-000002",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-03-01",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "val": 30,
                                "accn": "0001-24-000003",
                                "fy": 2024,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2024-05-01",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "val": 999,
                                "accn": "0001-24-000004",
                                "form": "8-K",
                                "filed": "2024-05-02",
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 500,
                                "accn": "0001-24-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 300,
                                "accn": "0001-24-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "PaymentsForRepurchaseOfCommonStock": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 12,
                                "accn": "0001-24-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "GrossProfit": {"units": {"USD": []}},
            }
        },
    }


def _submissions() -> list[dict]:
    return [
        {
            "filings": {
                "recent": {
                    "accessionNumber": [
                        "0001-24-000001",
                        "0001-24-000002",
                        "0001-24-000003",
                    ],
                    "acceptanceDateTime": [
                        "2024-02-01T18:00:00Z",
                        "2024-03-01T18:00:00Z",
                        "2024-05-01T18:00:00Z",
                    ],
                }
            }
        }
    ]


def test_future_filings_are_excluded_and_revision_becomes_available_after_acceptance():
    facts = normalize_company_facts("EXM", _company_facts(), _submissions())

    before_first = facts_as_of(facts, "2024-02-01T17:59:59Z")
    assert before_first.empty

    after_first = facts_as_of(facts, "2024-02-01T18:00:00Z")
    assert set(after_first["accession_number"]) == {"0001-24-000001"}

    before_revision = facts_as_of(facts, "2024-02-29")
    assert set(before_revision["accession_number"]) == {"0001-24-000001"}

    after_revision = facts_as_of(facts, "2024-03-01")
    assert set(after_revision["accession_number"]) == {"0001-24-000001", "0001-24-000002"}


def test_10k_10q_filtering_units_and_accessions_are_retained():
    facts = normalize_company_facts("EXM", _company_facts(), _submissions())

    assert set(facts["form"]) == {"10-K", "10-Q"}
    assert "0001-24-000004" not in set(facts["accession_number"])
    assert set(facts["unit"]) == {"USD", "shares"}
    shares = facts.loc[facts["field"] == "shares_outstanding"].iloc[0]
    assert shares["taxonomy"] == "dei"
    assert shares["value"] == 50
    assert facts.loc[facts["field"] == "liabilities", "value"].iloc[0] == 300
    assert facts.loc[facts["field"] == "share_repurchases", "value"].iloc[0] == 12
    assert {"0001-24-000001", "0001-24-000002", "0001-24-000003"} <= set(
        facts["accession_number"]
    )
    only_10q = facts_as_of(facts, "2024-06-01", forms={"10-Q"})
    assert set(only_10q["form"]) == {"10-Q"}


def test_missing_facts_remain_missing_not_zero():
    facts = normalize_company_facts("EXM", _company_facts(), _submissions())

    gross_profit = facts.loc[facts["field"] == "gross_profit"]
    assert gross_profit.empty
    assert not (facts["field"] == "gross_profit").any()
    assert not (facts["value"] == 0).any()


def test_date_only_filed_fallback_is_not_available_until_next_day():
    facts = normalize_company_facts("EXM", _company_facts(), [])

    assert facts_as_of(facts, "2024-02-01").empty
    next_day = facts_as_of(facts, "2024-02-02")
    assert "0001-24-000001" in set(next_day["accession_number"])


def test_sec_client_declares_user_agent_and_uses_cache(tmp_path):
    calls = []

    def transport(request, timeout):
        calls.append((request, timeout))
        return json.dumps({"0": {"ticker": "EXM", "cik_str": 1}}).encode()

    client = SecEdgarClient(
        user_agent="Research Team research@example.com",
        cache_dir=tmp_path,
        transport=transport,
    )
    first = client.ticker_cik_map()
    second = client.ticker_cik_map()

    assert first == second == {"EXM": "0000000001"}
    assert len(calls) == 1
    assert calls[0][0].get_header("User-agent") == "Research Team research@example.com"
    assert (tmp_path / "company_tickers.json").exists()


def test_event_panel_uses_first_trading_date_after_publication_and_labels_fallback():
    facts = normalize_company_facts("EXM", _company_facts(), _submissions())
    dates = pd.bdate_range("2024-02-01", "2024-05-06")
    events = build_filing_event_panel(facts, dates)
    first = events.loc[events["accession_number"].eq("0001-24-000001")]
    assert set(first["first_valid_trading_date"]) == {pd.Timestamp("2024-02-02")}
    assert set(first["availability_label"]) == {"ACCEPTED_TIMESTAMP"}
    fallback = build_filing_event_panel(normalize_company_facts("EXM", _company_facts(), []), dates)
    assert "FILED_DATE_PLUS_ONE_CONSERVATIVE_FALLBACK" in set(fallback["availability_label"])
    assert (events["first_valid_trading_date"] > pd.to_datetime(events["availability_datetime"]).dt.tz_convert(None).dt.normalize()).all()
