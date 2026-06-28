"""Deterministic mechanism language for Strategy Intelligence V1."""

from __future__ import annotations

from typing import Any


def _flatten_values(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        items: list[str] = []
        for key, child in value.items():
            if key in {"daily_returns", "net_equity", "drawdown", "rolling_63d_sharpe"}:
                continue
            items.extend(_flatten_values(child))
        return items
    if isinstance(value, list):
        items = []
        for child in value:
            items.extend(_flatten_values(child))
        return items
    return [str(value)]


def metadata_text(row: dict[str, Any], research_summary: dict[str, Any] | None = None) -> str:
    fields = [
        row.get("family"),
        row.get("name"),
        row.get("display_name"),
        row.get("strategy_name"),
        row.get("variant_id"),
        row.get("signal_definition"),
        row.get("hypothesis_summary"),
        row.get("source_system"),
        row.get("source"),
    ]
    if research_summary:
        raw = research_summary.get("raw_summary_row") or {}
        for key in (
            "version",
            "strategy_id",
            "signal",
            "signal_definition",
            "signal_summary",
            "research_status",
            "decision",
            "labels",
            "recommendation",
            "execution_mode",
            "average_daily_turnover",
            "cost_drag_ratio",
        ):
            fields.append(research_summary.get(key))
            fields.append(raw.get(key))
    return " ".join(str(value or "") for value in fields).replace("_", " ").replace("-", " ").lower()


def research_decision(research_summary: dict[str, Any] | None = None) -> str:
    if not research_summary:
        return "MISSING_RESEARCH_DECISION"
    raw = research_summary.get("raw_summary_row") or {}
    for value in (raw.get("decision"), research_summary.get("decision"), research_summary.get("research_status")):
        if value not in (None, "", [], {}):
            return str(value).upper()
    return "MISSING_RESEARCH_DECISION"


def _specific_signal(text: str) -> str:
    if "relative strength" in text:
        return "relative strength momentum"
    if "slow momentum" in text:
        return "slow momentum"
    if "residual momentum" in text:
        return "residual momentum"
    if "price efficiency" in text:
        return "price-efficiency signal"
    if "efficient price path" in text:
        return "efficient price path signal"
    if "amihud" in text or "illiquidity" in text:
        return "Amihud illiquidity signal"
    if "filing" in text:
        return "filing or post-filing signal"
    if "cash flow" in text:
        return "cash-flow quality signal"
    if "earnings" in text:
        return "earnings quality signal"
    if "margin" in text:
        return "margin improvement signal"
    if "overnight" in text or "intraday" in text or "gap" in text:
        return "overnight/intraday microstructure signal"
    if "trend" in text:
        return "trend signal"
    return "documented research signal"


def classify_mechanism(row: dict[str, Any], research_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    text = metadata_text(row, research_summary)
    strategy_uid = str(row.get("strategy_uid") or row.get("strategy_id") or row.get("internal_id") or "")
    signal = _specific_signal(text)
    if strategy_uid == "COMBINED_PORTFOLIO" or "combined" in text:
        return {
            "family": row.get("family") or "Combined",
            "mechanism_class": "COMBINED_COMPOSITE",
            "mechanism_source": "portfolio_composite_metadata",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": "Diversified composite of current active paper strategies rather than a standalone alpha signal.",
            "economic_mechanism": (
                "Causal Thesis: portfolio-level diversification may reduce idiosyncratic strategy noise; "
                "it is not independent evidence of a new alpha source, and returns depend on constituents."
            ),
            "causal_thesis_confidence": "COMPOSITE_MECHANISM_ONLY",
            "failure_modes": [
                "constituent overlap",
                "correlation spike",
                "hidden factor concentration",
                "insufficient attribution",
            ],
        }
    if row.get("strategy_factory_phase2"):
        return {
            "family": row.get("family") or "Strategy Factory",
            "mechanism_class": "STRATEGY_FACTORY_ACTIVE_UNALLOCATED",
            "mechanism_source": "strategy_factory_activation_lineage",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": (
                f"User-confirmed {signal} waiting for paper allocation evidence; current weight remains zero."
            ),
            "economic_mechanism": (
                "Causal Thesis: candidate-specific source material may define an edge, but V1 requires "
                "explicit evidence artifacts before treating the thesis as supported."
            ),
            "causal_thesis_confidence": "MISSING_EVIDENCE",
            "failure_modes": [
                "no NAV/P&L impact while current weight is zero",
                "missing PIT/timestamp evidence",
                "insufficient attribution",
                "ML evidence missing",
            ],
        }
    if any(word in text for word in ("liquidity", "illiquidity", "amihud", "volume")):
        return {
            "family": row.get("family") or "Liquidity",
            "mechanism_class": "LIQUIDITY",
            "mechanism_source": "research_metadata",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": (
                f"Uses {signal} to capture compensation or persistence linked to liquidity preference and trading frictions."
            ),
            "economic_mechanism": (
                "Causal Thesis: liquidity-related signals may reflect investor constraints, capacity pressure, "
                "or compensation for trading frictions; evidence is partial until attribution and cost-linkage are decomposed."
            ),
            "causal_thesis_confidence": "HYPOTHESIS_ONLY",
            "failure_modes": [
                "capacity limitation",
                "transaction cost sensitivity",
                "liquidity regime shift",
                "public fallback data limitation",
            ],
        }
    if "price efficiency" in text or "efficient price path" in text:
        return {
            "family": row.get("family") or "Price Efficiency",
            "mechanism_class": "PRICE_EFFICIENCY",
            "mechanism_source": "research_metadata",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": (
                f"Uses {signal} to identify smoother or more efficient positive price paths rather than noisy drift."
            ),
            "economic_mechanism": (
                "Causal Thesis: cleaner trend formation, lower noisy path behavior, or gradual information diffusion "
                "may allow price paths with stronger persistence; this is not causal proof and needs attribution."
            ),
            "causal_thesis_confidence": "HYPOTHESIS_ONLY",
            "failure_modes": [
                "path signal can be data-mined",
                "choppy regime failure",
                "transaction cost sensitivity",
                "turnover evidence incomplete",
                "insufficient attribution",
            ],
        }
    if "fundamental momentum" in text:
        return {
            "family": row.get("family") or "Fundamental Momentum",
            "mechanism_class": "FUNDAMENTAL_MOMENTUM",
            "mechanism_source": "research_metadata",
            "is_generic_fallback": False,
            "signal_metadata": "fundamental momentum signal",
            "edge_thesis": (
                "Combines revenue growth, margin change, and operating cash-flow improvement signals to detect "
                "fundamental trend persistence."
            ),
            "economic_mechanism": (
                "Causal Thesis: revenue growth, margin improvement, and operating cash-flow improvement may be "
                "incorporated gradually by the market; PIT and timestamp evidence remain required before treating "
                "this as an event-timing proof."
            ),
            "causal_thesis_confidence": "HYPOTHESIS_ONLY",
            "failure_modes": [
                "missing PIT/timestamp evidence",
                "fundamental data revision risk",
                "sector/beta confounding",
                "accounting noise",
                "insufficient attribution",
            ],
        }
    if any(word in text for word in ("fundamental", "earnings", "filing", "cash flow", "margin", "quality")):
        return {
            "family": row.get("family") or "Fundamental / Event",
            "mechanism_class": "FUNDAMENTAL_EVENT",
            "mechanism_source": "research_metadata",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": f"Uses {signal} to capture delayed market incorporation of fundamentals or event information.",
            "economic_mechanism": (
                "Causal Thesis: accounting or filing information may be incorporated with a delay, "
                "creating post-event drift or quality re-rating; PIT/timestamp evidence remains a gating concern."
            ),
            "causal_thesis_confidence": "HYPOTHESIS_ONLY",
            "failure_modes": [
                "missing PIT/timestamp evidence",
                "stale filings",
                "accounting noise",
                "sector/beta confounding",
            ],
        }
    if any(word in text for word in ("overnight", "intraday", "reversal", "gap", "microstructure")):
        return {
            "family": row.get("family") or "Market Microstructure",
            "mechanism_class": "MARKET_MICROSTRUCTURE",
            "mechanism_source": "research_metadata",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": f"Uses {signal} to capture short-horizon overreaction, liquidity pressure, or session effects.",
            "economic_mechanism": (
                "Causal Thesis: temporary overreaction and liquidity pressure may mean-revert over short horizons; "
                "cost and execution sensitivity can erase the effect."
            ),
            "causal_thesis_confidence": "HYPOTHESIS_ONLY",
            "failure_modes": [
                "high turnover",
                "transaction cost sensitivity",
                "microstructure decay",
                "execution sensitivity",
            ],
        }
    if any(word in text for word in ("momentum", "trend", "strength", "continuation")):
        return {
            "family": row.get("family") or "Momentum",
            "mechanism_class": "MOMENTUM",
            "mechanism_source": "research_metadata",
            "is_generic_fallback": False,
            "signal_metadata": signal,
            "edge_thesis": f"Uses {signal} to capture price persistence that may reflect slow information diffusion.",
            "economic_mechanism": (
                "Causal Thesis: medium-term momentum may reflect delayed information diffusion, investor underreaction, "
                "or gradual portfolio rebalancing; research decisions remain separate from allocation approval."
            ),
            "causal_thesis_confidence": "HYPOTHESIS_ONLY",
            "failure_modes": [
                "momentum reversal",
                "crowding",
                "regime decay",
                "sector/beta confounding",
            ],
        }
    return {
        "family": row.get("family") or "General Alpha Research",
        "mechanism_class": "GENERAL_ALPHA_RESEARCH",
        "mechanism_source": "generic_fallback",
        "is_generic_fallback": True,
        "signal_metadata": signal,
        "edge_thesis": "Captures a documented research signal, with mechanism evidence requiring explicit artifacts.",
        "economic_mechanism": (
            "Causal Thesis: V1 can state a research hypothesis only; supporting mechanism metadata is incomplete."
        ),
        "causal_thesis_confidence": "MISSING_EVIDENCE",
        "failure_modes": [
            "regime decay",
            "missing PIT/timestamp evidence",
            "insufficient attribution",
            "public fallback data limitation",
        ],
    }
