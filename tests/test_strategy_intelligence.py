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


def _write_selected_batch_job(root: Path, job: dict) -> None:
    job_dir = root / "data" / "strategy_factory" / "jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / f"{job['job_id']}.json").write_text(json.dumps(job, indent=2), encoding="utf-8")


def _write_risk_evidence_artifact(root: Path, artifact: dict) -> Path:
    path = root / "data" / "automation" / "risk_evidence" / "20260630T000000.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return path


def _risk_metric(metric: str, status: str, value: float | None = None) -> dict:
    return {
        "metric": metric,
        "status": status,
        "value": value,
        "observation_count": 5,
        "min_observations_required": 20 if metric in {"historical_var_95", "historical_cvar_95"} else 2,
        "missing_reason": None if status == "COMPUTED" else "Only 5 observations are available; 20 are required.",
    }


def _risk_artifact_for_test(strategy_uid: str, *, matched_strategy: bool = True) -> dict:
    labels = [
        "Prototype Only",
        "Paper Only",
        "Institutional Validation Pending",
        "Missing Risk Evidence",
        "Insufficient Risk History",
    ]
    portfolio = {
        "status": "PARTIAL",
        "observation_count": 5,
        "window_start": "2026-06-04",
        "window_end": "2026-06-11",
        "risk_metrics": {
            "historical_var_95": _risk_metric("historical_var_95", "INSUFFICIENT_HISTORY"),
            "historical_cvar_95": _risk_metric("historical_cvar_95", "INSUFFICIENT_HISTORY"),
            "max_drawdown": _risk_metric("max_drawdown", "COMPUTED", -0.02),
            "realized_volatility": _risk_metric("realized_volatility", "COMPUTED", 0.01),
        },
        "labels": labels,
    }
    return {
        "ok": True,
        "source": "risk_evidence_artifact_v0",
        "schema_version": "0.1.0",
        "generated_at": "2026-06-30T00:00:00+00:00",
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "input_source": "unit_test",
        "input_artifacts": ["unit-test"],
        "observation_count": 5,
        "window_start": "2026-06-04",
        "window_end": "2026-06-11",
        "methodology": {"annualized": False, "confidence_level": 0.95},
        "portfolio_risk_evidence": portfolio,
        "strategy_risk_evidence": [
            {
                **portfolio,
                "strategy_uid": strategy_uid if matched_strategy else f"not-{strategy_uid}",
            }
        ],
        "missing_data": [
            {
                "scope": "portfolio_tail_metrics",
                "status": "INSUFFICIENT_HISTORY",
                "missing_reason": "5 observations found; 20 are required for historical VaR/CVaR.",
            }
        ],
        "labels": labels,
    }


def _lineage_item(
    *,
    artifact_type: str,
    artifact_path: str | None,
    exists: bool,
    strategy_uid: str,
    candidate_id: str,
    status: str,
    labels: list[str],
) -> dict:
    return {
        "artifact_type": artifact_type,
        "artifact_path": artifact_path,
        "exists": exists,
        "material_id": None,
        "material_ids": ["test-material-id"],
        "strategy_uid": strategy_uid,
        "candidate_id": candidate_id,
        "status": status,
        "missing_reason": None if exists else f"{artifact_type} missing in focused test",
        "labels": labels,
    }


def test_strategy_intelligence_cards_include_selected_batch_evidence_manifest(tmp_path: Path):
    root = _copy_root(tmp_path)
    baseline = build_strategy_intelligence_payload(root)
    uid = baseline["cards"][0]["strategy_uid"]
    candidate_id = f"candidate-for-{uid}"
    artifact = root / "output" / "strategy_factory" / "runs" / "lineage-test" / "evidence_report.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# Evidence\n", encoding="utf-8")
    _write_selected_batch_job(
        root,
        {
            "ok": True,
            "source": "strategy_factory_selected_batch_job_v1",
            "job_id": "lineage-test-job",
            "generated_at": "2026-06-30T00:00:00+00:00",
            "selected_material_count": 1,
            "selected_material_ids": ["test-material-id"],
            "selected_material_hashes": ["test-material-hash"],
            "outputs": {
                "research_cards": [],
                "test_specs": [],
                "evidence_reports": [
                    _lineage_item(
                        artifact_type="evidence_report",
                        artifact_path=str(artifact),
                        exists=True,
                        strategy_uid=uid,
                        candidate_id=candidate_id,
                        status="AVAILABLE",
                        labels=["Prototype Only"],
                    )
                ],
                "backtest_outputs": [],
                "ml_gate_outputs": [
                    _lineage_item(
                        artifact_type="ml_gate_output",
                        artifact_path=None,
                        exists=False,
                        strategy_uid=uid,
                        candidate_id=candidate_id,
                        status="MISSING_ARTIFACT",
                        labels=["Prototype Only", "Missing ML Evidence"],
                    )
                ],
                "robustness_outputs": [
                    _lineage_item(
                        artifact_type="robustness_output",
                        artifact_path=None,
                        exists=False,
                        strategy_uid=uid,
                        candidate_id=candidate_id,
                        status="MISSING_ARTIFACT",
                        labels=["Prototype Only", "Missing Robustness Evidence"],
                    )
                ],
                "candidate_registry_updates": [],
            },
        },
    )

    payload = build_strategy_intelligence_payload(root)
    card = _cards_by_uid(payload)[uid]
    manifest = card["evidence_manifest"]

    assert manifest["evidence_sources"]
    assert manifest["factory_lineage_sources"]
    assert manifest["evidence_status"] == "Research Evidence Available"
    assert manifest["ml_evidence_status"] == "Missing ML Evidence"
    assert manifest["attribution_status"] == "Missing Attribution"
    assert manifest["regime_evidence_status"] == "Missing Regime Evidence"
    assert manifest["robustness_status"] == "Missing Robustness Evidence"
    assert manifest["interpretability_evidence"]["shap_status"] == "MISSING_ARTIFACT"
    assert manifest["interpretability_evidence"]["permutation_importance_status"] == "MISSING_ARTIFACT"
    assert manifest["interpretability_evidence"]["feature_importance_artifact"] is None
    assert "Missing ML Evidence" in manifest["interpretability_evidence"]["interpretability_labels"]
    assert manifest["risk_evidence"]["var_status"] == "MISSING_ARTIFACT"
    assert manifest["risk_evidence"]["cvar_status"] == "MISSING_ARTIFACT"
    assert manifest["risk_evidence"]["drawdown_stress_status"] == "MISSING_ARTIFACT"
    assert manifest["risk_evidence"]["risk_artifact"] is None
    assert manifest["regime_evidence"]["regime_tag_status"] == "MISSING_ARTIFACT"
    assert manifest["regime_evidence"]["current_regime_relevance_status"] == "MISSING_ARTIFACT"
    assert manifest["regime_evidence"]["regime_artifact"] is None
    assert manifest["attribution_evidence"]["return_attribution_status"] == "MISSING_ARTIFACT"
    assert manifest["attribution_evidence"]["factor_attribution_status"] == "MISSING_ARTIFACT"
    assert manifest["attribution_evidence"]["pnl_source_status"] == "MISSING_ARTIFACT"
    assert manifest["attribution_evidence"]["attribution_artifact"] is None
    assert card["evidence_sources"][0]["artifact_type"] == "evidence_report"
    assert card["evidence_sources"][0]["exists"] is True
    assert "Missing ML Evidence" in card["missing_evidence"]
    assert "Missing Attribution" in card["missing_evidence"]
    assert "Missing Regime Evidence" in card["missing_evidence"]
    assert "Missing Risk Evidence" in card["missing_evidence"]
    assert "Missing Robustness Evidence" in card["missing_evidence"]


def test_strategy_intelligence_risk_evidence_missing_without_artifact(tmp_path: Path):
    root = _copy_root(tmp_path)

    payload = build_strategy_intelligence_payload(root)
    risk = payload["cards"][0]["evidence_manifest"]["risk_evidence"]

    assert risk["var_status"] == "MISSING_ARTIFACT"
    assert risk["cvar_status"] == "MISSING_ARTIFACT"
    assert risk["drawdown_stress_status"] == "MISSING_ARTIFACT"
    assert risk["realized_volatility_status"] == "MISSING_ARTIFACT"
    assert risk["risk_artifact"] is None
    assert risk["portfolio_risk_context"] is None
    assert risk["strategy_risk_context"] is None
    assert "Missing Risk Evidence" in risk["labels"]


def test_strategy_intelligence_links_portfolio_risk_artifact_insufficient_history(tmp_path: Path):
    root = _copy_root(tmp_path)
    baseline = build_strategy_intelligence_payload(root)
    uid = baseline["cards"][0]["strategy_uid"]
    _write_risk_evidence_artifact(root, _risk_artifact_for_test(uid))

    payload = build_strategy_intelligence_payload(root)
    risk = _cards_by_uid(payload)[uid]["evidence_manifest"]["risk_evidence"]

    assert risk["risk_artifact"]["artifact_type"] == "risk_evidence_artifact"
    assert risk["var_status"] == "INSUFFICIENT_HISTORY"
    assert risk["cvar_status"] == "INSUFFICIENT_HISTORY"
    assert risk["drawdown_stress_status"] == "COMPUTED"
    assert risk["realized_volatility_status"] == "COMPUTED"
    assert risk["portfolio_risk_context"]["risk_metrics"]["historical_var_95"]["status"] == "INSUFFICIENT_HISTORY"
    assert "Insufficient Risk History" in risk["labels"]
    assert risk["var_status"] != "AVAILABLE"


def test_strategy_intelligence_attaches_strategy_risk_by_strategy_uid_only(tmp_path: Path):
    root = _copy_root(tmp_path)
    baseline = build_strategy_intelligence_payload(root)
    uid = baseline["cards"][0]["strategy_uid"]
    _write_risk_evidence_artifact(root, _risk_artifact_for_test(uid))

    payload = build_strategy_intelligence_payload(root)
    risk = _cards_by_uid(payload)[uid]["evidence_manifest"]["risk_evidence"]

    assert risk["strategy_risk_context"]["status"] == "PARTIAL"
    assert risk["strategy_risk_context"]["risk_metrics"]["max_drawdown"]["value"] == -0.02


def test_strategy_intelligence_does_not_attach_unmatched_strategy_risk(tmp_path: Path):
    root = _copy_root(tmp_path)
    baseline = build_strategy_intelligence_payload(root)
    uid = baseline["cards"][0]["strategy_uid"]
    _write_risk_evidence_artifact(root, _risk_artifact_for_test(uid, matched_strategy=False))

    payload = build_strategy_intelligence_payload(root)
    risk = _cards_by_uid(payload)[uid]["evidence_manifest"]["risk_evidence"]

    assert risk["portfolio_risk_context"]["status"] == "PARTIAL"
    assert risk["strategy_risk_context"] is None
    assert "No strategy-level risk evidence matched this card by strategy_uid." in risk["missing_reason"]


def test_unmatched_selected_batch_job_is_visible_but_not_attached_as_fake_evidence(tmp_path: Path):
    root = _copy_root(tmp_path)
    _write_selected_batch_job(
        root,
        {
            "ok": True,
            "source": "strategy_factory_selected_batch_job_v1",
            "job_id": "unmatched-lineage-test-job",
            "generated_at": "2026-06-30T00:00:00+00:00",
            "selected_material_count": 1,
            "selected_material_ids": ["unmatched-material-id"],
            "selected_material_hashes": ["unmatched-material-hash"],
            "outputs": {
                "research_cards": [
                    _lineage_item(
                        artifact_type="research_card",
                        artifact_path="output/strategy_factory/unmatched/research_card.md",
                        exists=True,
                        strategy_uid="unmatched-strategy-uid",
                        candidate_id="unmatched-candidate-id",
                        status="AVAILABLE",
                        labels=["Prototype Only"],
                    )
                ],
                "test_specs": [],
                "evidence_reports": [],
                "backtest_outputs": [],
                "ml_gate_outputs": [],
                "robustness_outputs": [],
                "candidate_registry_updates": [],
            },
        },
    )

    payload = build_strategy_intelligence_payload(root)
    first = payload["cards"][0]
    manifest = first["evidence_manifest"]

    assert manifest["evidence_sources"] == []
    assert manifest["factory_lineage_sources"][0]["artifact_type"] == "selected_batch_job"
    assert manifest["factory_lineage_sources"][0]["match_status"] == "NO_SAFE_IDENTIFIER_MATCH"
    assert manifest["ml_evidence_status"] == "Missing ML Evidence"
    assert manifest["attribution_status"] == "Missing Attribution"
    assert manifest["regime_evidence_status"] == "Missing Regime Evidence"
    assert manifest["robustness_status"] == "Missing Robustness Evidence"


def test_strategy_intelligence_advanced_evidence_sections_include_existing_artifacts(tmp_path: Path):
    root = _copy_root(tmp_path)
    baseline = build_strategy_intelligence_payload(root)
    uid = baseline["cards"][0]["strategy_uid"]
    candidate_id = f"candidate-for-{uid}"
    artifact = root / "output" / "strategy_factory" / "runs" / "advanced-lineage" / "artifact.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    outputs = {
        "research_cards": [],
        "test_specs": [],
        "evidence_reports": [],
        "backtest_outputs": [],
        "ml_gate_outputs": [
            _lineage_item(
                artifact_type="ml_gate_output",
                artifact_path=str(artifact),
                exists=True,
                strategy_uid=uid,
                candidate_id=candidate_id,
                status="AVAILABLE",
                labels=["Prototype Only"],
            )
        ],
        "robustness_outputs": [],
        "candidate_registry_updates": [],
        "risk_outputs": [
            _lineage_item(
                artifact_type="risk_output",
                artifact_path=str(artifact),
                exists=True,
                strategy_uid=uid,
                candidate_id=candidate_id,
                status="AVAILABLE",
                labels=["Prototype Only"],
            )
        ],
        "regime_outputs": [
            _lineage_item(
                artifact_type="regime_evidence",
                artifact_path=str(artifact),
                exists=True,
                strategy_uid=uid,
                candidate_id=candidate_id,
                status="AVAILABLE",
                labels=["Prototype Only"],
            )
        ],
        "attribution_outputs": [
            _lineage_item(
                artifact_type="attribution_output",
                artifact_path=str(artifact),
                exists=True,
                strategy_uid=uid,
                candidate_id=candidate_id,
                status="AVAILABLE",
                labels=["Prototype Only"],
            )
        ],
    }
    _write_selected_batch_job(
        root,
        {
            "ok": True,
            "source": "strategy_factory_selected_batch_job_v1",
            "job_id": "advanced-lineage-test-job",
            "generated_at": "2026-06-30T00:00:00+00:00",
            "selected_material_count": 1,
            "selected_material_ids": ["test-material-id"],
            "selected_material_hashes": ["test-material-hash"],
            "outputs": outputs,
        },
    )

    payload = build_strategy_intelligence_payload(root)
    manifest = _cards_by_uid(payload)[uid]["evidence_manifest"]

    assert manifest["interpretability_evidence"]["feature_importance_artifact"]["exists"] is True
    assert manifest["interpretability_evidence"]["feature_importance_artifact"]["source"] == "selected_batch_lineage"
    assert manifest["interpretability_evidence"]["interpretability_labels"] == ["Prototype Only"]
    assert manifest["risk_evidence"]["risk_artifact"] is None
    assert manifest["risk_evidence"]["var_status"] == "MISSING_ARTIFACT"
    assert manifest["regime_evidence"]["regime_artifact"]["artifact_type"] == "regime_evidence"
    assert manifest["regime_evidence"]["regime_tag_status"] == "PENDING"
    assert manifest["attribution_evidence"]["attribution_artifact"]["artifact_type"] == "attribution_output"
    assert manifest["attribution_evidence"]["return_attribution_status"] == "PENDING"


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
