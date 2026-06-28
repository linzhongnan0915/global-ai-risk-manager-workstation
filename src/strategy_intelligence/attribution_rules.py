"""Return Attribution rules for Strategy Intelligence Preview."""

from __future__ import annotations

from typing import Any

from src.strategy_intelligence.schema import ATTRIBUTION_REQUIRED_EVIDENCE


ATTRIBUTION_KEYS = {
    "long_leg_evidence",
    "short_leg_evidence",
    "factor_exposure_status",
    "sector_exposure_status",
    "beta_exposure_status",
    "liquidity_exposure_status",
    "regime_evidence_status",
    "cost_sensitivity_status",
    "concentration_status",
}


def attribution_summary(row: dict[str, Any], research_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    sources = [row, row.get("research_evidence") or {}, (row.get("research_evidence") or {}).get("research_metrics") or {}]
    if research_summary:
        sources.extend([research_summary, research_summary.get("raw_summary_row") or {}])
    fields: dict[str, Any] = {}
    for key in ATTRIBUTION_KEYS:
        value = next((source.get(key) for source in sources if source.get(key) not in (None, "", [], {})), None)
        fields[key] = value if value is not None else "Missing Attribution Evidence"
    if all(value == "Missing Attribution Evidence" for value in fields.values()):
        status = "Missing Attribution Evidence"
    else:
        status = "PARTIAL_ATTRIBUTION_EVIDENCE"
    return {
        "status": status,
        "requirement": "Requires factor/sector/long-short decomposition",
        "fields": fields,
        "missing_evidence": list(ATTRIBUTION_REQUIRED_EVIDENCE) if status == "Missing Attribution Evidence" else [],
    }
