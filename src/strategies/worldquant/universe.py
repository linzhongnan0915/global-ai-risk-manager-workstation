"""US-listed security master builder for WorldQuant Alpha #2 research.

This module builds a **current-listed** US equity universe from Nasdaq Trader
symbol-directory files. It is intentionally separate from the ETF proxy dataset
in ``data/processed/market_price_history.csv``.

Survivorship bias
-----------------
The output reflects **today's listings only**. Delisted, merged, and bankrupt
names are absent. Any historical Alpha #2 backtest must document this limitation
or replace this master with a point-in-time universe source in a later phase.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pandas as pd

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

FOOTER_PREFIX = "File Creation Time:"

NASDAQ_LISTED_SOURCE = "nasdaqlisted.txt"
OTHER_LISTED_SOURCE = "otherlisted.txt"

DEFAULT_MASTER_OUTPUT = Path("data/reference/worldquant_alpha2_us_security_master.csv")
DEFAULT_CANDIDATES_OUTPUT = Path("data/reference/worldquant_alpha2_common_stock_candidates.csv")

OTHER_EXCHANGE_MAP = {
    "N": "NYSE",
    "A": "NYSE American",
    "P": "NYSE Arca",
    "Z": "BATS",
    "V": "IEX",
    "B": "NASDAQ BX",
    "C": "NSX",
    "D": "FINRA ADF",
    "I": "International Securities Exchange",
    "J": "Direct Edge A",
    "K": "Direct Edge X",
    "M": "Chicago Stock Exchange",
    "S": "NASDAQ Small Cap / other",
    "T": "NASDAQ",
    "Q": "NASDAQ Global Select",
    "G": "NASDAQ Global",
    "H": "NYSE MKT / AMEX historical",
}

MASTER_COLUMNS = [
    "symbol_raw",
    "symbol_normalized",
    "security_name",
    "listing_exchange",
    "source_file",
    "etf_flag",
    "test_issue_flag",
    "financial_status",
    "market_category",
    "cqs_symbol",
    "nasdaq_symbol",
    "is_adr",
    "is_reit",
    "classification",
    "eligible_candidate",
    "exclusion_reason",
    "needs_review",
    "duplicate_symbol",
]


@dataclass(frozen=True)
class ClassificationResult:
    classification: str
    eligible_candidate: bool
    exclusion_reason: str
    needs_review: bool
    is_adr: bool
    is_reit: bool = False


def is_footer_row(line: str) -> bool:
    return line.strip().startswith(FOOTER_PREFIX)


def normalize_symbol(symbol: str) -> str:
    """Uppercase trim for matching; preserve dots, dashes, and other characters."""
    return symbol.strip().upper()


def _read_pipe_table(text: str) -> pd.DataFrame:
    cleaned_lines = [line for line in text.splitlines() if line.strip() and not is_footer_row(line)]
    if not cleaned_lines:
        return pd.DataFrame()
    return pd.read_csv(io.StringIO("\n".join(cleaned_lines)), sep="|", dtype=str).fillna("")


def parse_nasdaq_listed_text(text: str) -> pd.DataFrame:
    """Parse ``nasdaqlisted.txt`` content into a normalized raw frame."""
    raw = _read_pipe_table(text)
    if raw.empty:
        return raw

    records: list[dict[str, str]] = []
    for _, row in raw.iterrows():
        symbol = str(row.get("Symbol", "")).strip()
        if not symbol:
            continue
        records.append(
            {
                "symbol_raw": symbol,
                "symbol_normalized": normalize_symbol(symbol),
                "security_name": str(row.get("Security Name", "")).strip(),
                "listing_exchange": "NASDAQ",
                "source_file": NASDAQ_LISTED_SOURCE,
                "etf_flag": str(row.get("ETF", "")).strip().upper(),
                "test_issue_flag": str(row.get("Test Issue", "")).strip().upper(),
                "financial_status": str(row.get("Financial Status", "")).strip(),
                "market_category": str(row.get("Market Category", "")).strip(),
                "cqs_symbol": "",
                "nasdaq_symbol": symbol,
            }
        )
    return pd.DataFrame(records)


def parse_other_listed_text(text: str) -> pd.DataFrame:
    """Parse ``otherlisted.txt`` content into a normalized raw frame."""
    raw = _read_pipe_table(text)
    if raw.empty:
        return raw

    records: list[dict[str, str]] = []
    for _, row in raw.iterrows():
        symbol = str(row.get("ACT Symbol", "")).strip()
        if not symbol:
            continue
        exchange_code = str(row.get("Exchange", "")).strip().upper()
        records.append(
            {
                "symbol_raw": symbol,
                "symbol_normalized": normalize_symbol(symbol),
                "security_name": str(row.get("Security Name", "")).strip(),
                "listing_exchange": OTHER_EXCHANGE_MAP.get(exchange_code, exchange_code or "UNKNOWN"),
                "source_file": OTHER_LISTED_SOURCE,
                "etf_flag": str(row.get("ETF", "")).strip().upper(),
                "test_issue_flag": str(row.get("Test Issue", "")).strip().upper(),
                "financial_status": "",
                "market_category": "",
                "cqs_symbol": str(row.get("CQS Symbol", "")).strip(),
                "nasdaq_symbol": str(row.get("NASDAQ Symbol", "")).strip(),
            }
        )
    return pd.DataFrame(records)


def download_symbol_directory_text(url: str, *, timeout: int = 60) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def download_symbol_directories() -> tuple[str, str]:
    nasdaq_text = download_symbol_directory_text(NASDAQ_LISTED_URL)
    other_text = download_symbol_directory_text(OTHER_LISTED_URL)
    return nasdaq_text, other_text


_INSTRUMENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("warrant", re.compile(r"\bwarrants?\b", re.I)),
    ("rights", re.compile(r"\brights?\b|\bacquisition right\b|\bsubscription right\b", re.I)),
    ("units", re.compile(r"\bunits?\b|\btrust units?\b", re.I)),
]

_PREFERRED_PATTERN = re.compile(
    r"\bpreferred stock\b|\bpreferred shares?\b|\bpfd\b|\bpref\.?\b|\bpreference shares?\b",
    re.I,
)
_NOTES_DEBT_PATTERN = re.compile(
    r"\bnotes due\b|\bsenior notes?\b|\bsubordinated notes?\b|\bdebentures?\b|"
    r"\bcorporate bond\b|\bloan stock\b|\bconvertible senior\b|"
    r"\b\d+(?:\.\d+)?%\s*(?:senior\s+)?notes?\b",
    re.I,
)
_POOLED_INVESTMENT_PATTERN = re.compile(
    r"\bclosed[- ]end fund\b|\bmutual fund\b|\betf\b|\betn\b|exchange[- ]traded fund|"
    r"\bincome fund\b|\bfund, inc\.\s*common shares?\b|\binvestment company\b|"
    r"\bfund\b.*\bcommon shares of beneficial interest\b|"
    r"\bcommon shares of beneficial interest\b.*\bfund\b|"
    r"\b(income trust|bond trust|capital trust| dividend trust|municipal bond trust|gold trust)\b",
    re.I,
)
_OPERATING_REIT_TRUST_PATTERN = re.compile(
    r"\b(?:[\w.&'-]+\s+){0,4}"
    r"(?:properties|healthcare|hospitality|hotel|storage|industrial|office|service|homes \d+\s+rent)"
    r"(?:\s+[\w.&'-]+){0,2}\s+trust\b|\btrust\s+-\s+shares of beneficial interest\b",
    re.I,
)
_NON_REIT_INVESTMENT_TRUST_PATTERN = re.compile(
    r"(?<!real estate )\binvestment trust\b",
    re.I,
)

_REIT_MARKER_PATTERN = re.compile(r"\breit\b|\breal estate investment trust\b", re.I)
_BENEFICIAL_INTEREST_PATTERN = re.compile(r"\bshares of beneficial interest\b", re.I)
_COMMON_EQUITY_PATTERN = re.compile(
    r"\bcommon stock\b|\bcommon shares?\b|\bordinary shares?\b|\bclass [a-z]\s+(?:common|ordinary) shares?\b",
    re.I,
)

_SPAC_SHELL_PATTERN = re.compile(
    r"\b(?:blank[- ]check\b|"
    r"acquisition\b(?:\s+(?:[\w.&-]+\s+)*)?"
    r"(?:corp(?:oration)?|inc(?:\.|orporated)?|ltd|limited|group|co(?:mpany)?)"
    r"(?:\.|\b))",
    re.I,
)
_SHARE_INSTRUMENT_PATTERN = re.compile(
    r"\bcommon stock\b|\bcommon shares?\b|\bordinary shares?\b|\bclass [a-z]\s+(?:common|ordinary) shares?\b",
    re.I,
)

_ADR_PATTERN = re.compile(
    r"\bamerican depositary shares?\b|\badrs?\b|\bdepositary shares?\b|\bglobal depositary shares?\b",
    re.I,
)
_COMMON_STOCK_PATTERN = re.compile(
    r"\bcommon stock\b|\bcommon shares?\b|\bordinary shares?\b|\bclass [a-z] common\b",
    re.I,
)
_AMBIGUOUS_NAME_PATTERN = re.compile(
    r"\b(class [a-z] ordinary shares?|limited partnership|lp units?)\b",
    re.I,
)


def _matches_instrument_pattern(name: str, reason: str, pattern: re.Pattern[str]) -> bool:
    if reason == "warrant" and "warranty" in name.lower():
        return False
    return bool(pattern.search(name))


def _is_operating_reit_trust(name: str) -> bool:
    if re.search(
        r"\b(gabelli|guggenheim|blackrock|pimco|nuveen|virtus|abrdn|invesco|franklin|allspring|"
        r"graniteshares|clough|robinhood|pimco|medias)\b",
        name,
        re.I,
    ):
        return False
    return bool(_OPERATING_REIT_TRUST_PATTERN.search(name))


def _is_pooled_trust_beneficial_interest(name: str) -> bool:
    return bool(
        _BENEFICIAL_INTEREST_PATTERN.search(name)
        and re.search(r"\btrust\b", name, re.I)
        and not _REIT_MARKER_PATTERN.search(name)
        and not _is_operating_reit_trust(name)
    )


def _is_non_reit_investment_trust(name: str) -> bool:
    if _REIT_MARKER_PATTERN.search(name):
        return False
    return bool(_NON_REIT_INVESTMENT_TRUST_PATTERN.search(name))


def _is_reit_common_equity(name: str) -> bool:
    if _PREFERRED_PATTERN.search(name) or _NOTES_DEBT_PATTERN.search(name):
        return False
    if _POOLED_INVESTMENT_PATTERN.search(name) or _is_non_reit_investment_trust(name):
        return False

    has_reit_marker = bool(_REIT_MARKER_PATTERN.search(name))
    has_beneficial_interest = bool(_BENEFICIAL_INTEREST_PATTERN.search(name))

    if has_beneficial_interest:
        if re.search(r"\bfund\b", name, re.I):
            return False
        if has_reit_marker:
            return True
        if _is_operating_reit_trust(name):
            return True
        if re.search(r"\bhomes \d+\s+rent\b", name, re.I):
            return True
        return False

    if not has_reit_marker:
        return False

    if _COMMON_EQUITY_PATTERN.search(name):
        return True

    if re.search(r"\(REIT\)|\breit,?\s+inc(?:\.|orporated)?\s*$|\breit\s*$", name, re.I):
        return True

    if re.search(r"\breal estate investment trust\s*$", name, re.I):
        return True

    return False


def classify_security(row: pd.Series | dict[str, Any]) -> ClassificationResult:
    """Conservatively classify one security row."""
    if isinstance(row, pd.Series):
        data = row.to_dict()
    else:
        data = row

    name = str(data.get("security_name", "")).strip()
    etf_flag = str(data.get("etf_flag", "")).strip().upper()
    test_issue_flag = str(data.get("test_issue_flag", "")).strip().upper()
    is_adr = bool(_ADR_PATTERN.search(name))

    if etf_flag == "Y":
        return ClassificationResult("etf_flag", False, "etf_flag", False, is_adr, False)
    if test_issue_flag == "Y":
        return ClassificationResult("test_issue", False, "test_issue", False, is_adr, False)

    for reason, pattern in _INSTRUMENT_PATTERNS:
        if _matches_instrument_pattern(name, reason, pattern):
            return ClassificationResult(reason, False, reason, False, is_adr, False)

    if _PREFERRED_PATTERN.search(name):
        return ClassificationResult("preferred_share", False, "preferred_share", False, is_adr, False)

    if _NOTES_DEBT_PATTERN.search(name):
        return ClassificationResult("notes_debt", False, "notes_debt", False, is_adr, False)

    if _POOLED_INVESTMENT_PATTERN.search(name) or _is_pooled_trust_beneficial_interest(name):
        return ClassificationResult("closed_end_fund", False, "closed_end_fund", False, is_adr, False)

    if _is_non_reit_investment_trust(name):
        return ClassificationResult("fund_trust", False, "fund_trust", False, is_adr, False)

    if _SPAC_SHELL_PATTERN.search(name) and _SHARE_INSTRUMENT_PATTERN.search(name):
        return ClassificationResult("spac_shell", False, "spac_shell", False, is_adr, False)

    if is_adr:
        if _COMMON_STOCK_PATTERN.search(name) or "representing" in name.lower():
            return ClassificationResult("adr_depositary", True, "", False, True, False)
        return ClassificationResult("adr_depositary", False, "", True, True, False)

    if _is_reit_common_equity(name):
        return ClassificationResult("reit_common_equity", True, "", False, is_adr, True)

    if _COMMON_STOCK_PATTERN.search(name):
        return ClassificationResult("common_stock", True, "", False, is_adr, False)

    if _AMBIGUOUS_NAME_PATTERN.search(name):
        return ClassificationResult("needs_review_ambiguous", False, "", True, is_adr, False)

    if name.endswith(" Inc.") or name.endswith(" Corp.") or name.endswith(" Corporation"):
        return ClassificationResult("needs_review_ambiguous", False, "", True, is_adr, False)

    return ClassificationResult("needs_review_ambiguous", False, "", True, is_adr, False)


def _apply_classification(frame: pd.DataFrame) -> pd.DataFrame:
    classified_rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        result = classify_security(row)
        classified_rows.append(
            {
                **row.to_dict(),
                "is_adr": result.is_adr,
                "is_reit": result.is_reit,
                "classification": result.classification,
                "eligible_candidate": result.eligible_candidate,
                "exclusion_reason": result.exclusion_reason,
                "needs_review": result.needs_review,
            }
        )
    return pd.DataFrame(classified_rows)


def mark_duplicate_symbols(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame["symbol_normalized"].value_counts()
    duplicate_symbols = set(counts[counts > 1].index)
    output = frame.copy()
    output["duplicate_symbol"] = output["symbol_normalized"].isin(duplicate_symbols)
    return output


def build_security_master(nasdaq_frame: pd.DataFrame, other_frame: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([nasdaq_frame, other_frame], ignore_index=True, sort=False)
    combined = _apply_classification(combined)
    combined = mark_duplicate_symbols(combined)
    return combined[MASTER_COLUMNS]


def filter_common_stock_candidates(master: pd.DataFrame) -> pd.DataFrame:
    mask = master["eligible_candidate"].astype(bool) & ~master["duplicate_symbol"].astype(bool)
    return master.loc[mask].copy()


def build_audit_summary(master: pd.DataFrame) -> dict[str, int]:
    nasdaq_rows = int((master["source_file"] == NASDAQ_LISTED_SOURCE).sum())
    other_rows = int((master["source_file"] == OTHER_LISTED_SOURCE).sum())
    duplicate_symbol_count = int(master["duplicate_symbol"].astype(bool).sum())

    exclusion_counts = master.loc[master["exclusion_reason"] != "", "exclusion_reason"].value_counts()
    non_common_exclusions = master.loc[
        (master["exclusion_reason"] != "")
        & (~master["exclusion_reason"].isin(["etf_flag", "test_issue"]))
    ]

    return {
        "nasdaq_listed_rows": nasdaq_rows,
        "other_exchange_rows": other_rows,
        "total_unique_symbols": int(master["symbol_normalized"].nunique()),
        "total_rows": int(len(master)),
        "etf_exclusions": int(exclusion_counts.get("etf_flag", 0)),
        "test_issue_exclusions": int(exclusion_counts.get("test_issue", 0)),
        "non_common_security_exclusions": int(len(non_common_exclusions)),
        "non_common_exclusions_by_reason": {
            reason: int(count) for reason, count in non_common_exclusions["exclusion_reason"].value_counts().items()
        },
        "adr_count": int(master["is_adr"].astype(bool).sum()),
        "needs_review_count": int(master["needs_review"].astype(bool).sum()),
        "eligible_candidate_count": int(master["eligible_candidate"].astype(bool).sum()),
        "reit_common_equity_count": int((master["classification"] == "reit_common_equity").sum()),
        "fund_closed_end_exclusion_count": int(
            master["exclusion_reason"].isin(["closed_end_fund", "fund_trust"]).sum()
        ),
        "duplicate_symbol_rows": duplicate_symbol_count,
    }


def format_audit_summary(summary: dict[str, Any]) -> str:
    lines = [
        "WorldQuant Alpha #2 US security master audit",
        f"  Nasdaq-listed rows: {summary['nasdaq_listed_rows']}",
        f"  Other-exchange rows: {summary['other_exchange_rows']}",
        f"  Total rows: {summary['total_rows']}",
        f"  Total unique symbols: {summary['total_unique_symbols']}",
        f"  ETF exclusions: {summary['etf_exclusions']}",
        f"  Test-issue exclusions: {summary['test_issue_exclusions']}",
        f"  Non-common-security exclusions: {summary['non_common_security_exclusions']}",
        f"  ADR / depositary count: {summary['adr_count']}",
        f"  Needs-review count: {summary['needs_review_count']}",
        f"  Eligible-candidate count: {summary['eligible_candidate_count']}",
        f"  REIT common-equity count: {summary['reit_common_equity_count']}",
        f"  Fund / closed-end exclusions: {summary['fund_closed_end_exclusion_count']}",
        f"  Duplicate-symbol rows: {summary['duplicate_symbol_rows']}",
    ]
    by_reason = summary.get("non_common_exclusions_by_reason") or {}
    if by_reason:
        lines.append("  Non-common exclusions by reason:")
        for reason, count in sorted(by_reason.items()):
            lines.append(f"    - {reason}: {count}")
    lines.append(
        "  Note: current-listed universe only; subject to survivorship bias for historical backtests."
    )
    return "\n".join(lines)


def write_universe_outputs(
    master: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    master_path: Path = DEFAULT_MASTER_OUTPUT,
    candidates_path: Path = DEFAULT_CANDIDATES_OUTPUT,
) -> tuple[Path, Path]:
    master_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(master_path, index=False)
    candidates.to_csv(candidates_path, index=False)
    return master_path, candidates_path


def build_universe_from_text(nasdaq_text: str, other_text: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    nasdaq_frame = parse_nasdaq_listed_text(nasdaq_text)
    other_frame = parse_other_listed_text(other_text)
    master = build_security_master(nasdaq_frame, other_frame)
    candidates = filter_common_stock_candidates(master)
    summary = build_audit_summary(master)
    return master, candidates, summary


def build_universe_from_download() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    nasdaq_text, other_text = download_symbol_directories()
    return build_universe_from_text(nasdaq_text, other_text)
