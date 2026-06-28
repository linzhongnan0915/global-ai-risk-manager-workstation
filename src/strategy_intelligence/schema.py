"""Shared constants for Strategy Intelligence Preview V1."""

from __future__ import annotations

SCHEMA_VERSION = "strategy_intelligence_cards_v1"
COVERAGE_UNIVERSE = "current_top_level_active_plus_active_unallocated"
ARTIFACT_RELATIVE_PATH = "data/strategy_intelligence/strategy_explanation_cards.json"

ML_REQUIRED_EVIDENCE = [
    "feature specification missing",
    "target specification missing",
    "train/validation/test split missing",
    "OOS / walk-forward metrics missing",
    "baseline comparison missing",
    "model artifact missing",
    "explainability / feature importance missing",
]

ATTRIBUTION_REQUIRED_EVIDENCE = [
    "Missing long/short contribution decomposition",
    "Missing factor exposure attribution",
    "Missing sector attribution",
    "Missing regime attribution",
    "Missing cost-sensitivity linkage",
]
