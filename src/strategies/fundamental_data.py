"""Minimal point-in-time SEC EDGAR fundamental data layer."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
import gzip
import json
from pathlib import Path
import time
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd
import numpy as np

SEC_DATA_BASE = "https://data.sec.gov"
SEC_XBRL_BASE = "https://data.sec.gov/api/xbrl"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_CACHE_DIR = Path("data/raw/sec_edgar_cache")
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.11
SUPPORTED_FORMS = frozenset({"10-K", "10-Q"})
SMOKE_TEST_TICKERS = ("AAPL", "MSFT", "JPM")

FIELD_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "assets": ("Assets",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "liabilities": ("Liabilities",),
    "receivables": ("AccountsReceivableNetCurrent", "AccountsNotesAndLoansReceivableNetCurrent"),
    "inventory": ("InventoryNet",),
    "dividends_paid": (
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfOrdinaryDividends",
    ),
    "share_repurchases": ("PaymentsForRepurchaseOfCommonStock",),
    "shares_outstanding": ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"),
}

FUNDAMENTAL_COLUMNS = [
    "ticker",
    "cik",
    "company_name",
    "field",
    "taxonomy",
    "taxonomy_tag",
    "fiscal_period_start",
    "fiscal_period_end",
    "fiscal_year",
    "fiscal_period",
    "form",
    "accession_number",
    "filed_date",
    "accepted_datetime",
    "availability_datetime",
    "unit",
    "value",
    "frame",
]

Transport = Callable[[Request, float], bytes]


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            return gzip.decompress(payload)
        return payload


def _safe_cache_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value)


@dataclass
class SecEdgarClient:
    """Cached SEC JSON client that follows the SEC fair-access request limit."""

    user_agent: str
    cache_dir: Path = DEFAULT_CACHE_DIR
    min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    timeout_seconds: float = 30.0
    transport: Transport = _default_transport
    _last_request_time: float | None = None

    def __post_init__(self) -> None:
        if not self.user_agent.strip() or "@" not in self.user_agent:
            raise ValueError("SEC user_agent must identify the requester and include a contact email")
        if self.min_request_interval_seconds < DEFAULT_MIN_REQUEST_INTERVAL_SECONDS:
            raise ValueError("SEC request interval must be at least 0.11 seconds")
        self.cache_dir = Path(self.cache_dir)

    def get_json(self, url: str, cache_name: str, *, refresh: bool = False) -> dict[str, Any]:
        cache_path = self.cache_dir / _safe_cache_name(cache_name)
        if cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        now = time.monotonic()
        if self._last_request_time is not None:
            wait = self.min_request_interval_seconds - (now - self._last_request_time)
            if wait > 0:
                time.sleep(wait)

        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        payload = self.transport(request, self.timeout_seconds)
        self._last_request_time = time.monotonic()
        parsed = json.loads(payload.decode("utf-8"))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(parsed), encoding="utf-8")
        return parsed

    def ticker_cik_map(self, *, refresh: bool = False) -> dict[str, str]:
        payload = self.get_json(SEC_TICKER_URL, "company_tickers.json", refresh=refresh)
        return {
            str(row["ticker"]).upper(): f"{int(row['cik_str']):010d}"
            for row in payload.values()
        }

    def company_facts(self, cik: str, *, refresh: bool = False) -> dict[str, Any]:
        padded = f"{int(cik):010d}"
        return self.get_json(
            f"{SEC_XBRL_BASE}/companyfacts/CIK{padded}.json",
            f"CIK{padded}_companyfacts.json",
            refresh=refresh,
        )

    def submissions(self, cik: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        padded = f"{int(cik):010d}"
        main = self.get_json(
            f"{SEC_DATA_BASE}/submissions/CIK{padded}.json",
            f"CIK{padded}_submissions.json",
            refresh=refresh,
        )
        payloads = [main]
        for item in main.get("filings", {}).get("files", []):
            name = item.get("name")
            if name:
                payloads.append(
                    self.get_json(
                        f"{SEC_DATA_BASE}/submissions/{name}",
                        name,
                        refresh=refresh,
                    )
                )
        return payloads


def _submission_rows(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    recent = payload.get("filings", {}).get("recent")
    table = recent if isinstance(recent, dict) else payload
    accessions = table.get("accessionNumber", [])
    for index, accession in enumerate(accessions):
        yield {
            key: values[index] if isinstance(values, list) and index < len(values) else None
            for key, values in table.items()
        } | {"accessionNumber": accession}


def build_acceptance_lookup(submissions_payloads: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map accession number to SEC acceptance timestamp, including historical submission files."""
    lookup: dict[str, str] = {}
    for payload in submissions_payloads:
        for row in _submission_rows(payload):
            accession = row.get("accessionNumber")
            accepted = row.get("acceptanceDateTime")
            if accession and accepted:
                lookup[str(accession)] = str(accepted)
    return lookup


def _availability_datetime(accepted: Any, filed: Any) -> pd.Timestamp:
    if accepted:
        return pd.to_datetime(accepted, utc=True)
    if filed:
        # A date-only filed value has no safe intraday publication time.
        return pd.to_datetime(filed, utc=True) + pd.Timedelta(days=1)
    return pd.NaT


def normalize_company_facts(
    ticker: str,
    company_facts: dict[str, Any],
    submissions_payloads: Iterable[dict[str, Any]],
    *,
    forms: Iterable[str] = SUPPORTED_FORMS,
) -> pd.DataFrame:
    """Normalize supported US-GAAP facts while preserving every filing revision."""
    allowed_forms = {str(form) for form in forms}
    acceptance_lookup = build_acceptance_lookup(submissions_payloads)
    taxonomies = company_facts.get("facts", {})
    rows: list[dict[str, Any]] = []

    for field, tags in FIELD_TAGS.items():
        for tag in tags:
            for taxonomy in ("us-gaap", "dei"):
                fact = taxonomies.get(taxonomy, {}).get(tag)
                if not fact:
                    continue
                for unit, observations in fact.get("units", {}).items():
                    for observation in observations:
                        form = observation.get("form")
                        if form not in allowed_forms:
                            continue
                        accession = observation.get("accn")
                        accepted = acceptance_lookup.get(str(accession)) if accession else None
                        rows.append(
                            {
                                "ticker": ticker.upper(),
                                "cik": f"{int(company_facts['cik']):010d}",
                                "company_name": company_facts.get("entityName"),
                                "field": field,
                                "taxonomy": taxonomy,
                                "taxonomy_tag": tag,
                                "fiscal_period_start": observation.get("start"),
                                "fiscal_period_end": observation.get("end"),
                                "fiscal_year": observation.get("fy"),
                                "fiscal_period": observation.get("fp"),
                                "form": form,
                                "accession_number": accession,
                                "filed_date": observation.get("filed"),
                                "accepted_datetime": accepted,
                                "availability_datetime": _availability_datetime(
                                    accepted, observation.get("filed")
                                ),
                                "unit": unit,
                                "value": observation.get("val"),
                                "frame": observation.get("frame"),
                            }
                        )

    frame = pd.DataFrame(rows, columns=FUNDAMENTAL_COLUMNS)
    if frame.empty:
        return frame
    for column in ("fiscal_period_start", "fiscal_period_end", "filed_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    frame["accepted_datetime"] = pd.to_datetime(frame["accepted_datetime"], errors="coerce", utc=True)
    frame["availability_datetime"] = pd.to_datetime(frame["availability_datetime"], errors="coerce", utc=True)
    return frame.sort_values(
        ["ticker", "field", "fiscal_period_end", "availability_datetime", "accession_number"],
        na_position="last",
    ).reset_index(drop=True)


def facts_as_of(
    facts: pd.DataFrame,
    signal_date: str | date | pd.Timestamp,
    *,
    forms: Iterable[str] = SUPPORTED_FORMS,
) -> pd.DataFrame:
    """Return only facts publicly available by the requested signal timestamp."""
    if facts.empty:
        return facts.copy()
    cutoff = pd.to_datetime(signal_date, utc=True)
    is_date_only = (
        isinstance(signal_date, date)
        and not isinstance(signal_date, (datetime, pd.Timestamp))
        or isinstance(signal_date, str)
        and len(signal_date.strip()) == 10
    )
    if is_date_only:
        cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    allowed_forms = {str(form) for form in forms}
    available = facts["availability_datetime"].notna() & facts["availability_datetime"].le(cutoff)
    return facts.loc[available & facts["form"].isin(allowed_forms)].copy().reset_index(drop=True)


def build_filing_event_panel(facts: pd.DataFrame, trading_dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    """Aggregate facts by accession and align each filing to the first trading date after publication."""
    columns = [
        "ticker", "stable_id", "form", "accession_number", "accepted_datetime", "filed_date",
        "availability_datetime", "availability_label", "first_valid_trading_date", "fiscal_period_end",
        "fiscal_period", "field", "unit", "value", "prior_value", "point_in_time_change",
    ]
    if facts.empty:
        return pd.DataFrame(columns=columns)
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).tz_localize(None).sort_values().unique()
    rows: list[dict[str, Any]] = []
    working = facts.dropna(subset=["accession_number", "availability_datetime"]).copy()
    for (ticker, accession), filing in working.groupby(["ticker", "accession_number"], sort=False):
        available = pd.Timestamp(filing["availability_datetime"].min())
        publication_day = available.tz_convert(None).normalize() if available.tzinfo else available.normalize()
        later = dates[dates > publication_day]
        if not len(later):
            continue
        first_trade = later[0]
        accepted = filing["accepted_datetime"].dropna()
        label = "ACCEPTED_TIMESTAMP" if len(accepted) else "FILED_DATE_PLUS_ONE_CONSERVATIVE_FALLBACK"
        previous = working.loc[
            working["ticker"].eq(ticker) & working["availability_datetime"].lt(available)
        ].sort_values("availability_datetime").drop_duplicates(["field"], keep="last").set_index("field")
        current = filing.sort_values(["field", "fiscal_period_end"]).drop_duplicates(["field"], keep="last")
        for fact in current.itertuples():
            prior = previous.loc[fact.field, "value"] if fact.field in previous.index else np.nan
            rows.append({
                "ticker": ticker, "stable_id": str(fact.cik), "form": fact.form,
                "accession_number": accession, "accepted_datetime": accepted.min() if len(accepted) else pd.NaT,
                "filed_date": fact.filed_date, "availability_datetime": available,
                "availability_label": label, "first_valid_trading_date": first_trade,
                "fiscal_period_end": fact.fiscal_period_end, "fiscal_period": fact.fiscal_period,
                "field": fact.field, "unit": fact.unit, "value": float(fact.value),
                "prior_value": float(prior) if pd.notna(prior) else np.nan,
                "point_in_time_change": (float(fact.value) - float(prior)) / abs(float(prior)) if pd.notna(prior) and float(prior) != 0 else np.nan,
            })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["first_valid_trading_date", "ticker", "accession_number", "field"]
    ).reset_index(drop=True)


def load_sec_fundamentals(
    tickers: Iterable[str],
    *,
    user_agent: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
) -> pd.DataFrame:
    """Download and normalize a small ticker set from SEC Company Facts and submissions."""
    client = SecEdgarClient(user_agent=user_agent, cache_dir=Path(cache_dir))
    cik_map = client.ticker_cik_map(refresh=refresh)
    frames: list[pd.DataFrame] = []
    for ticker in sorted({str(value).strip().upper() for value in tickers if str(value).strip()}):
        if ticker not in cik_map:
            raise KeyError(f"ticker not found in SEC company ticker map: {ticker}")
        cik = cik_map[ticker]
        frames.append(
            normalize_company_facts(
                ticker,
                client.company_facts(cik, refresh=refresh),
                client.submissions(cik, refresh=refresh),
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FUNDAMENTAL_COLUMNS)
