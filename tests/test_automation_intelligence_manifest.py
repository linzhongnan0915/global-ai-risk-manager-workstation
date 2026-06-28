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
from src.automation import (
    build_allocation_recommendation_artifact,
    build_automation_intelligence_manifest,
    build_daily_recommendation_artifact,
    read_latest_allocation_recommendation_artifact,
    read_latest_daily_recommendation_artifact,
    write_allocation_recommendation_artifact,
    write_daily_recommendation_artifact,
)
from src.reporting.operational_snapshot import load_snapshot_summary_for_response


ROOT = Path(__file__).resolve().parents[1]


def _copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "workstation"
    (root / "dashboard/data").mkdir(parents=True)
    (root / "dashboard/data/canonical_operational.json").write_text(
        (ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch_json(url: str) -> tuple[int, dict]:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _hashes(root: Path) -> dict[str, str]:
    base = root / "data"
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.glob("**/*.json"))
        if "automation/daily_recommendations" not in str(path.relative_to(root)).replace("\\", "/")
        and "automation/allocation_recommendations" not in str(path.relative_to(root)).replace("\\", "/")
    }


def _sample_strategy_intelligence_payload() -> dict:
    return {
        "ok": True,
        "cards": [
            {
                "strategy_uid": "sample-active",
                "strategy_name": "Sample Active",
                "current_weight": 0.2,
                "target_weight": 0.3,
                "decision_recommendation": "ACTIVE_MONITOR",
                "evidence_strength": "PARTIAL_EVIDENCE",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                "missing_evidence": ["model artifact missing", "Missing Attribution Evidence"],
                "source_artifacts": [{"kind": "test_fixture", "path": "test-only", "status": "TEST_ONLY"}],
            },
            {
                "strategy_uid": "sample-watch",
                "strategy_name": "Sample Watch",
                "current_weight": 0.1,
                "target_weight": None,
                "decision_recommendation": "WATCH_ONLY",
                "evidence_strength": "WATCH_ONLY",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                "missing_evidence": ["model artifact missing"],
                "source_artifacts": [],
            },
        ],
    }


def _sample_allocation_payload(weights: tuple[float | None, float | None] = (0.6, 0.4), *, second_source: str = "CANONICAL_OPERATIONAL") -> dict:
    first_weight, second_weight = weights
    return {
        "ok": True,
        "cards": [
            {
                "strategy_uid": "test-allocation-a",
                "strategy_name": "Test Allocation A",
                "source_status": "CANONICAL_OPERATIONAL",
                "current_weight": first_weight,
                "target_weight": first_weight,
                "decision_recommendation": "ACTIVE_MONITOR",
                "evidence_strength": "PARTIAL_EVIDENCE",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "ml_evidence": {"status": "MISSING_EVIDENCE"},
                "decomposition_evidence": {"status": "MISSING_EVIDENCE"},
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                "missing_evidence": ["model artifact missing", "Missing Attribution Evidence"],
                "source_artifacts": [{"kind": "test_fixture", "path": "test-only", "status": "TEST_ONLY"}],
            },
            {
                "strategy_uid": "test-allocation-b",
                "strategy_name": "Test Allocation B",
                "source_status": second_source,
                "current_weight": second_weight,
                "target_weight": second_weight,
                "decision_recommendation": "ACTIVE_MONITOR",
                "evidence_strength": "PARTIAL_EVIDENCE",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "ml_evidence": {"status": "MISSING_EVIDENCE"},
                "decomposition_evidence": {"status": "MISSING_EVIDENCE"},
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                "missing_evidence": ["model artifact missing", "Missing Attribution Evidence"],
                "source_artifacts": [],
            },
        ],
    }


def test_manifest_builder_returns_valid_schema_with_missing_alpha_files(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))

    manifest = build_automation_intelligence_manifest(root)

    assert manifest["source"] == "automation_intelligence_manifest_v0"
    assert manifest["paper_shadow_only"] is True
    assert manifest["live_trading_enabled"] is False
    assert manifest["financial_state_mutated"] is False
    assert manifest["daily_recommendation"]["status"] in {"MISSING_ARTIFACT", "AVAILABLE", "REVIEW_REQUIRED"}
    assert manifest["strategy_factory"]["status"] == "MISSING_ARTIFACT"
    assert manifest["ml_intelligence"]["status"] in {"MISSING_ARTIFACT", "MISSING_EVIDENCE"}
    assert manifest["decomposition"]["status"] in {"MISSING_ARTIFACT", "MISSING_EVIDENCE"}
    assert manifest["rebalance"]["mutation_allowed_from_get"] is False
    assert manifest["operator_summary"]["overall_status"] in {"OK", "REVIEW_REQUIRED", "BLOCKED", "MISSING_ARTIFACT"}


def test_manifest_reads_existing_paper_rebalance_artifacts(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    rebalance = root / "data/paper_rebalance"
    rebalance.mkdir(parents=True)
    (rebalance / "monthly_rebalance_proposals.json").write_text(
        json.dumps({"schema_version": "monthly_rebalance_proposal_v1", "proposals": [{"status": "MONTHLY_PROPOSAL_READY", "rows": []}]}),
        encoding="utf-8",
    )
    (rebalance / "recommendation_review_drafts.json").write_text(
        json.dumps({"schema_version": "recommendation_review_draft_v1", "drafts": [{"status": "DRAFT_NOT_APPLIED", "line_items": []}]}),
        encoding="utf-8",
    )
    (rebalance / "approved_rebalance_plans.json").write_text(
        json.dumps({"schema_version": "approved_rebalance_plan_v1", "plans": [{"plan_id": "plan-test", "status": "APPROVED_WAITING_EFFECTIVE_DATE", "effective_date": "2999-01-01", "rows": []}]}),
        encoding="utf-8",
    )

    manifest = build_automation_intelligence_manifest(root)

    assert manifest["rebalance"]["monthly_proposal_status"] == "MONTHLY_PROPOSAL_READY"
    assert manifest["rebalance"]["review_draft_status"] == "DRAFT_NOT_APPLIED"
    assert manifest["rebalance"]["approved_plan_status"] == "APPROVED_WAITING_EFFECTIVE_DATE"
    assert manifest["rebalance"]["apply_due_status"] == "NOT_DUE"
    assert manifest["rebalance"]["safe_to_apply_now"] is False


def test_manifest_endpoint_returns_200_and_get_does_not_mutate_paper_state(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    before = _hashes(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/manifest")
        after = _hashes(root)
        assert status == 200
        assert payload["ok"] is True
        assert payload["safety"]["get_mutates_state"] is False
        assert before == after
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes


def test_snapshot_summary_includes_compact_automation_intelligence_fields(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))

    summary = load_snapshot_summary_for_response(root)
    compact = summary["automation_intelligence"]

    assert compact["source"] == "automation_intelligence_manifest_v0"
    assert compact["overall_status"] in {"OK", "REVIEW_REQUIRED", "BLOCKED", "MISSING_ARTIFACT"}
    assert "daily_recommendation_status" in compact
    assert "rebalance_status" in compact
    assert "strategy_factory_status" in compact
    assert "ml_intelligence_status" in compact
    assert "decomposition_status" in compact
    assert isinstance(compact["review_required_count"], int)
    assert isinstance(compact["missing_evidence_count"], int)
    assert compact["financial_state_mutated"] is False


def test_manifest_logic_has_no_hardcoded_strategy_names_counts_or_display_ids() -> None:
    source = "\n".join(
        [
            (ROOT / "src/automation/automation_intelligence_manifest.py").read_text(encoding="utf-8"),
            (ROOT / "src/automation/daily_recommendation_artifact.py").read_text(encoding="utf-8"),
        ]
    )

    forbidden = ["C3A1_", "WQ_ALPHA_018", "COMBINED_PORTFOLIO", "#000", "ordinary_active_count: 18", "Copper", "Low Vol", "0.052631"]
    assert not any(token in source for token in forbidden)


def test_dashboard_renders_backend_automation_missing_states_without_frontend_counts() -> None:
    source = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "function automationIntelligenceStrip" in source
    assert "automation_intelligence" in source
    assert "Daily Recommendation" in source
    assert "daily_recommendation_preview" in source
    assert "Today's Strategy Actions" in source
    assert "ML Evidence" in source
    assert "Decomposition" in source
    assert "NOT_AVAILABLE" in source
    assert "review_required_count" in source
    assert "/api/automation-intelligence/manifest?ts=" not in source
    assert "/api/automation-intelligence/daily-recommendations/latest" not in source
    assert "recommended_action:\"INCREASE\"" not in source


def test_daily_recommendation_artifact_builder_creates_valid_schema_without_fake_increase(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)

    artifact = build_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=_sample_strategy_intelligence_payload(),
    )

    assert artifact["source"] == "daily_recommendation_artifact_v0"
    assert artifact["as_of_date"] == "2026-06-28"
    assert artifact["paper_shadow_only"] is True
    assert artifact["financial_state_mutated"] is False
    assert artifact["strategy_count"] == len(artifact["recommendations"])
    assert artifact["summary"]["increase_count"] == 0
    assert artifact["summary"]["hold_count"] == 1
    assert artifact["summary"]["review_count"] == 1
    assert artifact["summary"]["missing_ml_evidence_count"] == 2
    assert artifact["summary"]["missing_attribution_evidence_count"] == 2
    assert all(row["recommended_action"] != "INCREASE" for row in artifact["recommendations"])
    assert artifact["recommendations"][0]["proposed_weight"] == artifact["recommendations"][0]["current_weight"]


def test_write_and_read_latest_daily_recommendation_artifact(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    missing = read_latest_daily_recommendation_artifact(root)
    assert missing["ok"] is False
    assert missing["status"] == "MISSING_ARTIFACT"

    result = write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=_sample_strategy_intelligence_payload(),
    )
    latest = read_latest_daily_recommendation_artifact(root)

    assert result["status"] == "GENERATED"
    assert result["artifact_path"] == "data/automation/daily_recommendations/2026-06-28.json"
    assert latest["ok"] is True
    assert latest["artifact"]["summary"]["increase_count"] == 0


def test_post_generate_daily_recommendation_creates_artifact_without_financial_mutation(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    before = _hashes(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _post_json(f"http://127.0.0.1:{port}/api/automation-intelligence/daily-recommendations/generate")
        after = _hashes(root)
        assert status == 201
        assert payload["ok"] is True
        assert payload["financial_state_mutated"] is False
        assert before == after
        latest_status, latest = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/daily-recommendations/latest")
        assert latest_status == 200
        assert latest["artifact"]["source"] == "daily_recommendation_artifact_v0"
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes


def test_manifest_reads_daily_recommendation_artifact_counts(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=_sample_strategy_intelligence_payload(),
    )

    manifest = build_automation_intelligence_manifest(root)
    daily = manifest["daily_recommendation"]

    assert daily["status"] == "REVIEW_REQUIRED"
    assert daily["artifact_path"] == "data/automation/daily_recommendations/2026-06-28.json"
    assert daily["recommendation_count"] == 2
    assert daily["increase_count"] == 0
    assert daily["hold_count"] == 1
    assert daily["review_count"] == 1
    assert len(daily["preview"]) == 2


def test_allocation_recommendation_artifact_complete_weights_sum_to_100pct(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    payload = _sample_allocation_payload()
    write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    artifact = build_allocation_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    integrity = artifact["allocation_integrity"]
    assert artifact["source"] == "allocation_recommendation_artifact_v0"
    assert artifact["paper_shadow_only"] is True
    assert artifact["financial_state_mutated"] is False
    assert integrity["target_weight_sum"] == 1.0
    assert integrity["sums_to_100pct"] is True
    assert integrity["residual_weight"] == 0.0
    assert integrity["included_strategy_count"] == 2
    assert integrity["excluded_strategy_count"] == 0
    assert artifact["summary"]["allocation_change_recommended"] is False
    assert artifact["summary"]["review_draft_generation_allowed"] is False
    assert all(row["allocation_action"] == "NO_CHANGE" for row in artifact["recommendations"])
    assert not any("cash" in row["display_name"].lower() or "residual" in row["display_name"].lower() for row in artifact["recommendations"])


def test_allocation_recommendation_incomplete_weights_do_not_fake_100pct(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    payload = _sample_allocation_payload((0.6, None))
    write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    artifact = build_allocation_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    integrity = artifact["allocation_integrity"]
    assert integrity["target_weight_sum"] == 0.6
    assert integrity["sums_to_100pct"] is False
    assert round(integrity["residual_weight"], 10) == 0.4
    assert artifact["summary"]["allocation_change_recommended"] is False
    assert artifact["summary"]["review_draft_generation_allowed"] is False
    assert "Proposed allocation weights do not sum to 100%" in " ".join(artifact["warnings"])


def test_allocation_recommendation_missing_evidence_preserves_no_change_without_invalid_deltas(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    payload = _sample_allocation_payload()
    write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    artifact = build_allocation_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    assert artifact["summary"]["increase_candidate_count"] == 0
    assert artifact["summary"]["reduce_candidate_count"] == 0
    for row in artifact["recommendations"]:
        assert row["allocation_change_recommended"] is False
        assert row["proposed_weight"] == row["current_weight"]
        assert row["weight_delta"] == 0.0
        assert row["blocking_evidence"]


def test_allocation_denominator_excludes_non_canonical_unallocated_rows(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    payload = _sample_allocation_payload((1.0, 0.0), second_source="STRATEGY_FACTORY_ACTIVATION_RECORD")
    write_daily_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    artifact = build_allocation_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=payload,
    )

    rows = {row["strategy_uid"]: row for row in artifact["recommendations"]}
    assert rows["test-allocation-a"]["included_in_allocation_denominator"] is True
    assert rows["test-allocation-b"]["included_in_allocation_denominator"] is False
    assert artifact["allocation_integrity"]["included_strategy_count"] == 1
    assert artifact["allocation_integrity"]["excluded_strategy_count"] == 1
    assert artifact["allocation_integrity"]["sums_to_100pct"] is True


def test_write_and_read_latest_allocation_recommendation_artifact(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    missing = read_latest_allocation_recommendation_artifact(root)
    assert missing["ok"] is False
    assert missing["status"] == "MISSING_ARTIFACT"

    result = write_allocation_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=_sample_allocation_payload(),
    )
    latest = read_latest_allocation_recommendation_artifact(root)

    assert result["status"] == "GENERATED"
    assert result["artifact_path"] == "data/automation/allocation_recommendations/2026-06-28.json"
    assert latest["ok"] is True
    assert latest["artifact"]["allocation_integrity"]["sums_to_100pct"] is True


def test_post_generate_allocation_recommendation_creates_artifact_without_financial_mutation(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    before = _hashes(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _post_json(f"http://127.0.0.1:{port}/api/automation-intelligence/allocation-recommendations/generate")
        after = _hashes(root)
        assert status == 201
        assert payload["ok"] is True
        assert payload["financial_state_mutated"] is False
        assert payload["artifact"]["rebalance_plan_created"] is False
        assert before == after
        latest_status, latest = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/allocation-recommendations/latest")
        assert latest_status == 200
        assert latest["artifact"]["source"] == "allocation_recommendation_artifact_v0"
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes


def test_manifest_reads_allocation_recommendation_artifact_counts(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    write_allocation_recommendation_artifact(
        root,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
        strategy_intelligence_payload=_sample_allocation_payload(),
    )

    manifest = build_automation_intelligence_manifest(root)
    allocation = manifest["allocation_recommendation"]
    compact = load_snapshot_summary_for_response(root)["automation_intelligence"]

    assert allocation["status"] == "REVIEW_REQUIRED"
    assert allocation["artifact_path"] == "data/automation/allocation_recommendations/2026-06-28.json"
    assert allocation["no_change_count"] == 2
    assert allocation["review_required_count"] == 0
    assert allocation["allocation_integrity"]["sums_to_100pct"] is True
    assert compact["allocation_recommendation_status"] == "REVIEW_REQUIRED"
    assert compact["allocation_integrity"]["sums_to_100pct"] is True


def test_allocation_recommendation_logic_has_no_hardcoded_strategy_names_counts_or_weights() -> None:
    source = "\n".join(
        [
            (ROOT / "src/automation/allocation_recommendation_artifact.py").read_text(encoding="utf-8"),
            (ROOT / "src/automation/automation_intelligence_manifest.py").read_text(encoding="utf-8"),
        ]
    )

    forbidden = ["C3A", "WQ_ALPHA_018", "COMBINED_PORTFOLIO", "Copper", "Low Vol", "0.052631"]
    assert not any(token in source for token in forbidden)
    assert "included_strategy_count" in source
    assert "excluded_strategy_count" in source


def test_dashboard_allocation_recommendation_renders_backend_rows_only() -> None:
    source = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "Allocation Recommendation" in source
    assert "allocation_recommendation_preview" in source
    assert "allocation_integrity" in source
    assert "allocationPreview.map" in source
    assert "target_weight_sum:1" not in source
    assert "frontend_allocation_recommendations" not in source
    assert "allocation_recommendation_status:\"AVAILABLE\"" not in source
