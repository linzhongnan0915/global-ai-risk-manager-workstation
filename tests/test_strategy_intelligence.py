"""Tests for Strategy Intelligence / Explainability V1."""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler
from src.automation import read_latest_daily_recommendation_artifact, write_daily_recommendation_artifact
from src.reporting.operational_snapshot import load_snapshot_summary_for_response
from src.strategy_intelligence import build_strategy_intelligence_payload
from src.strategy_intelligence.mechanism_rules import classify_mechanism

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch_json(url: str) -> tuple[int, dict]:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def _paper_artifact_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): _file_hash(path)
        for path in sorted((ROOT / "data/paper_rebalance").glob("*.json"))
    }


def _cards_by_uid(payload: dict) -> dict[str, dict]:
    return {card["strategy_uid"]: card for card in payload["cards"]}


def _copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "workstation"
    (root / "dashboard/data").mkdir(parents=True)
    (root / "dashboard/data/canonical_operational.json").write_text(
        (ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def _card_by_research_version(payload: dict, token: str) -> dict:
    for card in payload["cards"]:
        for artifact in card["source_artifacts"]:
            if artifact["kind"] != "research_summary":
                continue
            path = ROOT / artifact["path"]
            summary = json.loads(path.read_text(encoding="utf-8"))
            version = ((summary.get("raw_summary_row") or {}).get("version") or "").lower()
            if token in version:
                return card
    raise AssertionError(f"No card with research version token {token!r}")


def test_payload_covers_current_top_level_universe_without_hardcoded_counts():
    payload = build_strategy_intelligence_payload(ROOT)
    summary = load_snapshot_summary_for_response(ROOT)

    assert payload["ok"] is True
    assert payload["coverage_universe"] == "current_top_level_active_plus_active_unallocated"
    assert len(payload["cards"]) == summary["counts"]["top_level_active_count"]
    assert payload["summary"]["strategies_explained"] == len(payload["cards"])
    assert payload["safety"]["full_snapshot_required"] is False
    assert payload["safety"]["state_mutation"] is False


def test_identity_uses_strategy_uid_not_display_label():
    payload = build_strategy_intelligence_payload(ROOT)

    for card in payload["cards"]:
        assert card["strategy_uid"]
        assert not card["strategy_uid"].startswith("#")
        assert card["display_label"] != card["strategy_uid"] or not card["display_label"].startswith("#")
        assert "card_id" in card


def test_missing_ml_and_missing_attribution_are_explicit_not_faked():
    payload = build_strategy_intelligence_payload(ROOT)

    assert payload["summary"]["ml_missing_evidence_count"] == len(payload["cards"])
    assert payload["summary"]["missing_attribution_count"] == len(payload["cards"])
    for card in payload["cards"]:
        assert card["ml_role"] == "ML_MISSING_EVIDENCE"
        assert "feature specification missing" in card["missing_evidence"]
        attribution = card["return_attribution_summary"]
        assert attribution["status"] == "Missing Attribution Evidence"
        assert attribution["requirement"] == "Requires factor/sector/long-short decomposition"
        assert "Missing long/short contribution decomposition" in attribution["missing_evidence"]
        assert card["ml_evidence"]["status"] == "MISSING_ML_EVIDENCE"
        assert card["decomposition_evidence"]["status"] == "MISSING_ATTRIBUTION_EVIDENCE"


def test_combined_is_composite_not_independent_alpha_source():
    payload = build_strategy_intelligence_payload(ROOT)
    combined = _cards_by_uid(payload)["COMBINED_PORTFOLIO"]

    text = json.dumps(combined).lower()
    assert "composite" in text
    assert "not independent" in text
    assert combined["decision_recommendation"] == "ACTIVE_MONITOR"
    assert "hidden factor concentration" in combined["failure_modes"]


def test_active_unallocated_rows_are_zero_weight_and_no_nav_pnl_until_apply():
    payload = build_strategy_intelligence_payload(ROOT)
    active_unallocated = [
        card
        for card in payload["cards"]
        if card["decision_recommendation"] == "ACTIVE_UNALLOCATED_ZERO_WEIGHT"
    ]

    assert active_unallocated
    for card in active_unallocated:
        assert card["current_weight"] == 0.0
        assert card["source_status"] == "STRATEGY_FACTORY_ACTIVATION_RECORD"
        assert card["decision_recommendation"] == "ACTIVE_UNALLOCATED_ZERO_WEIGHT"
        assert any("no NAV/P&L impact" in mode for mode in card["failure_modes"])
        assert any(a["kind"] == "strategy_factory_activation" for a in card["source_artifacts"])


def test_rejected_or_watch_research_stays_research_only():
    payload = build_strategy_intelligence_payload(ROOT)
    guarded = [
        card
        for card in payload["cards"]
        if card["decision_recommendation"] in {"WATCH_ONLY", "REJECT_RESEARCH_ONLY"}
    ]

    assert guarded
    assert all(card["evidence_strength"] in {"WATCH_ONLY", "REJECTED_EVIDENCE"} for card in guarded)


def test_metadata_version_classifies_opaque_relative_strength_as_momentum():
    payload = build_strategy_intelligence_payload(ROOT)
    card = _card_by_research_version(payload, "relative_strength")

    assert card["family"] == "Momentum"
    assert card["mechanism_class"] == "MOMENTUM"
    assert card["mechanism_source"] == "research_metadata"
    assert card["is_generic_fallback"] is False
    assert "relative strength" in card["signal_metadata"]


def test_metadata_version_classifies_low_amihud_as_liquidity():
    payload = build_strategy_intelligence_payload(ROOT)
    card = _card_by_research_version(payload, "amihud")

    assert card["family"] == "Liquidity"
    assert card["mechanism_class"] == "LIQUIDITY"
    assert "Amihud illiquidity" in card["signal_metadata"]


def test_metadata_version_classifies_slow_momentum_without_display_name_dependency():
    row = {"internal_id": "OPAQUE_INTERNAL", "name": "Opaque Strategy", "membership_state": "executed"}
    research = {"raw_summary_row": {"version": "opaque_slow_momentum_9_1_v1", "decision": "CONTINUE"}}

    mechanism = classify_mechanism(row, research)

    assert mechanism["mechanism_class"] == "MOMENTUM"
    assert mechanism["mechanism_source"] == "research_metadata"
    assert mechanism["is_generic_fallback"] is False


def test_fundamental_event_metadata_maps_without_false_ml_claim():
    payload = build_strategy_intelligence_payload(ROOT)
    event_cards = [card for card in payload["cards"] if card["mechanism_class"] == "FUNDAMENTAL_EVENT"]

    assert event_cards
    assert any("filing" in card["signal_metadata"].lower() or "cash-flow" in card["signal_metadata"].lower() for card in event_cards)
    assert all(card["ml_role"] == "ML_MISSING_EVIDENCE" for card in event_cards)


def test_price_efficiency_metadata_maps_without_strategy_id_dependency():
    row = {"internal_id": "OPAQUE_INTERNAL", "name": "Opaque Strategy", "membership_state": "executed"}
    research = {"raw_summary_row": {"version": "opaque_price_efficiency_v1", "decision": "CONTINUE"}}

    mechanism = classify_mechanism(row, research)

    assert mechanism["family"] == "Price Efficiency"
    assert mechanism["mechanism_class"] == "PRICE_EFFICIENCY"
    assert mechanism["mechanism_source"] == "research_metadata"
    assert mechanism["is_generic_fallback"] is False
    assert "smoother or more efficient positive price paths" in mechanism["edge_thesis"]
    assert "data-mined" in " ".join(mechanism["failure_modes"])


def test_actual_price_efficiency_card_is_not_generic_fallback():
    payload = build_strategy_intelligence_payload(ROOT)
    card = _card_by_research_version(payload, "price_efficiency")

    assert card["mechanism_class"] == "PRICE_EFFICIENCY"
    assert card["family"] == "Price Efficiency"
    assert card["is_generic_fallback"] is False


def test_fundamental_momentum_mechanism_names_supported_components():
    payload = build_strategy_intelligence_payload(ROOT)
    card = _cards_by_uid(payload)["FUNDAMENTAL_MOMENTUM"]
    text = f"{card['edge_thesis']} {card['economic_mechanism']}".lower()

    assert card["mechanism_class"] == "FUNDAMENTAL_MOMENTUM"
    assert card["family"] == "Fundamental Momentum"
    assert "revenue growth" in text
    assert "margin" in text
    assert "operating cash-flow" in text
    assert "pit" in text
    assert "event-timing proof" in text


def test_research_decision_is_exposed_from_source_artifact():
    payload = build_strategy_intelligence_payload(ROOT)
    relative_strength = _card_by_research_version(payload, "relative_strength")

    assert relative_strength["research_decision"] in {"ARCHIVE", "CONTINUE", "REJECT", "WATCH", "PARTIAL_EVIDENCE_ONLY", "READY"}
    assert relative_strength["evidence_decision"] == relative_strength["research_decision"]


def test_summary_quality_stats_are_reported_and_generic_fallback_reduced():
    payload = build_strategy_intelligence_payload(ROOT)
    summary = payload["summary"]

    assert summary["total_cards"] == len(payload["cards"])
    assert summary["generic_fallback_count"] == 0
    assert summary["cards_with_strategy_specific_mechanism"] == len(payload["cards"]) - summary["generic_fallback_count"]
    assert summary["active_unallocated_zero_weight_count"] == sum(
        card["decision_recommendation"] == "ACTIVE_UNALLOCATED_ZERO_WEIGHT" for card in payload["cards"]
    )
    assert isinstance(summary["research_decision_counts"], dict)


def test_no_specific_strategy_id_branch_in_mechanism_rules():
    source = (ROOT / "src/strategy_intelligence/mechanism_rules.py").read_text(encoding="utf-8")

    forbidden_ids = ["C3A1_013", "C3A1_002", "C3A1_003", "C3A2_008"]
    assert not any(strategy_id in source for strategy_id in forbidden_ids)


def test_cards_include_source_artifacts_and_no_execution_authority_language():
    payload = build_strategy_intelligence_payload(ROOT)
    serialized = json.dumps(payload).lower()

    assert all(card["source_artifacts"] for card in payload["cards"])
    assert "institutional approval" not in serialized
    assert "live trading approved" not in serialized
    assert "brokerage order" not in serialized
    assert payload["safety"]["execution_authority"] == "NONE"


def test_cards_include_daily_recommendation_fields_when_artifact_exists():
    payload = build_strategy_intelligence_payload(ROOT)
    latest = read_latest_daily_recommendation_artifact(ROOT)
    expected_artifact = latest.get("artifact_path")

    assert payload["summary"]["daily_recommendation_count"] == len(payload["cards"])
    for card in payload["cards"]:
        daily = card["daily_recommendation"]
        assert daily["source_artifact"] == expected_artifact
        assert daily["recommended_action"] in {"HOLD", "REVIEW", "REDUCE", "INCREASE"}
        assert daily["confidence"] in {"LOW", "MEDIUM", "HIGH", "REVIEW_REQUIRED"}
        assert daily["evidence_strength"] in {"MISSING", "WEAK", "PARTIAL", "STRONG"}
        assert card["operator_explanation"]["headline"].startswith("Today's action:")


def test_cards_show_missing_artifact_when_daily_recommendation_absent(tmp_path: Path):
    root = _copy_root(tmp_path)
    payload = build_strategy_intelligence_payload(root)

    assert payload["summary"]["daily_recommendation_status"] == "MISSING_ARTIFACT"
    assert payload["summary"]["daily_recommendation_count"] is None
    for card in payload["cards"]:
        assert card["daily_recommendation"]["status"] == "MISSING_ARTIFACT"
        assert card["daily_recommendation"]["recommended_action"] == "NOT_AVAILABLE"
        assert card["daily_recommendation"]["source_artifact"] is None


def test_daily_recommendation_matching_uses_strategy_uid_not_display_name(tmp_path: Path):
    root = _copy_root(tmp_path)
    baseline = build_strategy_intelligence_payload(root)
    first_uid = baseline["cards"][0]["strategy_uid"]
    fake_display_name = "Display Name Should Not Match Identity"
    write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload={
            "ok": True,
            "cards": [
                {
                    "strategy_uid": first_uid,
                    "strategy_name": fake_display_name,
                    "current_weight": 0.0,
                    "target_weight": None,
                    "decision_recommendation": "ACTIVE_MONITOR",
                    "evidence_strength": "PARTIAL_EVIDENCE",
                    "ml_evidence_status": "ML_MISSING_EVIDENCE",
                    "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                    "missing_evidence": ["model artifact missing"],
                    "source_artifacts": [],
                }
            ],
        },
    )

    payload = build_strategy_intelligence_payload(root)
    matched = _cards_by_uid(payload)[first_uid]

    assert matched["strategy_name"] != fake_display_name
    assert matched["daily_recommendation"]["recommended_action"] == "HOLD"
    assert payload["summary"]["daily_recommendation_missing_match_count"] == len(payload["cards"]) - 1


def test_strategy_intelligence_endpoint_is_200_and_read_only_for_paper_artifacts():
    before = _paper_artifact_hashes()
    original_root = WorkstationHandler.server_root
    port = _free_port()
    WorkstationHandler.server_root = ROOT
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _fetch_json(f"http://127.0.0.1:{port}/api/strategy-intelligence")
        assert status == 200
        assert payload["ok"] is True
        assert payload["cards"]
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
    after = _paper_artifact_hashes()

    assert after == before


def test_dashboard_strategy_intelligence_tab_is_summary_first_without_fake_rows():
    source = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    start = source.index("function strategyIntelligenceRows")
    end = source.index("function universePayload")
    page_source = source[start:end]

    assert '"Strategy Intelligence"' in source
    assert "/api/strategy-intelligence?ts=" in source
    assert '"Strategy Intelligence":strategyIntelligencePage' in source
    assert '["Universe & Data Coverage","Strategy Factory","Strategy Intelligence"]' in source
    assert '["Portfolio Command Center","Universe & Data Coverage","Strategy Factory","Strategy Intelligence"]' in source
    assert "Pending Detail" in page_source
    assert "no fake rows are rendered" in page_source
    assert "Strategy Intelligence Preview" in page_source
    assert "strategyIntelligenceEvidencePanel" in page_source
    assert "daily_recommendation" in page_source
    assert "ml_evidence" in page_source
    assert "decomposition_evidence" in page_source
    assert "/api/operational-snapshot" not in page_source
    assert "/api/automation-intelligence/daily-recommendations/latest" not in page_source


def test_strategy_intelligence_evidence_wiring_no_hardcoded_strategy_literals():
    sources = "\n".join(
        [
            (ROOT / "src/strategy_intelligence/builder.py").read_text(encoding="utf-8"),
            (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8"),
        ]
    )
    forbidden_new_logic = ["Copper", "Low Vol", "0.052631", "C3A1_", "ordinary_active_count: 18"]

    assert not any(token in sources for token in forbidden_new_logic)
    assert "row.get(\"strategy_uid\")" in sources
    assert "display_name\") == " not in sources
