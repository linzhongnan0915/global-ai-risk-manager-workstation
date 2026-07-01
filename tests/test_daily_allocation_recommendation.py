import hashlib
import json
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler
from src.automation.daily_allocation_recommendation import (
    build_daily_allocation_recommendation_artifact,
    read_latest_daily_allocation_recommendation,
    write_daily_allocation_recommendation_artifact,
)


ROOT = Path(__file__).resolve().parents[1]


def _copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "workstation"
    (root / "dashboard/data").mkdir(parents=True)
    (root / "dashboard/data/canonical_operational.json").write_text(
        (ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def _cards() -> dict:
    return {
        "ok": True,
        "cards": [
            {
                "strategy_uid": "uid-active-alpha",
                "internal_id": "internal-active-alpha",
                "strategy_name": "Display Can Change",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "executed",
                "current_weight": 0.12,
                "strategy_role": "ORDINARY",
                "sleeve_type": "TOP_LEVEL",
                "evidence_strength": "STRONG",
                "risk_status": "ok",
                "ml_evidence_status": "ML_EVIDENCE_AVAILABLE",
                "return_attribution_summary": {"status": "Attribution Available"},
                "daily_return": 0.01,
                "source_artifacts": [{"kind": "test", "path": "test-only/active.json"}],
            },
            {
                "strategy_uid": "uid-active-missing",
                "internal_id": "internal-active-missing",
                "strategy_name": "Another Mutable Display",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "executed",
                "current_weight": 0.08,
                "strategy_role": "ORDINARY",
                "sleeve_type": "TOP_LEVEL",
                "evidence_strength": "PARTIAL",
                "risk_status": "MISSING_RISK_EVIDENCE",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                "missing_evidence": ["Missing ML evidence", "Missing Attribution Evidence"],
            },
            {
                "strategy_uid": "uid-candidate",
                "candidate_id": "candidate-123",
                "strategy_name": "Candidate Display Only",
                "source_status": "STRATEGY_FACTORY_ACTIVATION_RECORD",
                "portfolio_status": "ACTIVE_UNALLOCATED",
                "current_weight": 0.0,
                "strategy_role": "RESEARCH",
                "sleeve_type": "PAPER_REVIEW_CANDIDATE",
                "evidence_strength": "PARTIAL",
                "risk_status": "watch",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
                "source_artifacts": [{"kind": "activation", "path": "test-only/candidate.json"}],
            },
            {
                "strategy_uid": "COMBINED_PORTFOLIO",
                "internal_id": "COMBINED_PORTFOLIO",
                "strategy_name": "Combined Portfolio",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "executed",
                "current_weight": 1.0,
                "strategy_role": "RESEARCH_COMPOSITE_CONSTRUCTED",
                "sleeve_type": "COMPOSITE",
                "is_combined": True,
                "evidence_strength": "PARTIAL",
                "risk_status": "ok",
                "ml_evidence_status": "ML_EVIDENCE_AVAILABLE",
                "return_attribution_summary": {"status": "Attribution Available"},
            },
            {
                "strategy_uid": "uid-excluded",
                "strategy_name": "Excluded Display",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "WATCH_ONLY",
                "current_weight": 0.0,
                "strategy_role": "RESEARCH",
                "evidence_strength": "WEAK",
                "risk_status": "MISSING_RISK_EVIDENCE",
                "ml_evidence_status": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
            },
        ],
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch_json(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _paper_rebalance_hashes(root: Path) -> dict[str, str]:
    base = root / "data" / "paper_rebalance"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.glob("**/*.json"))
    }


def test_artifact_includes_dynamic_eligible_rows_and_required_schema(tmp_path: Path) -> None:
    artifact = build_daily_allocation_recommendation_artifact(
        tmp_path,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    rows = {row["strategy_uid"]: row for row in artifact["rows"]}
    assert artifact["source"] == "daily_allocation_recommendation_artifact_v1"
    assert artifact["schema_version"] == "daily_allocation_recommendation_v1"
    assert artifact["recommendation_date"] == "2026-07-01"
    assert artifact["paper_shadow_only"] is True
    assert artifact["financial_state_mutated"] is False
    assert artifact["paper_apply_created"] is False
    assert artifact["approved_plan_created"] is False
    assert {"uid-active-alpha", "uid-active-missing", "uid-candidate", "COMBINED_PORTFOLIO", "uid-excluded"} <= set(rows)
    assert rows["uid-active-alpha"]["allocation_role"] == "ordinary_active"
    assert rows["uid-active-missing"]["allocation_role"] == "ordinary_active"


def test_identity_uses_canonical_uid_not_display_name() -> None:
    artifact = build_daily_allocation_recommendation_artifact(
        Path("."),
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    row = next(row for row in artifact["rows"] if row["strategy_name"] == "Display Can Change")
    assert row["strategy_uid"] == "uid-active-alpha"
    assert row["internal_id"] == "internal-active-alpha"
    assert row["strategy_name"] != row["strategy_uid"]


def test_active_unallocated_is_capped_review_or_zero_with_reason() -> None:
    artifact = build_daily_allocation_recommendation_artifact(
        Path("."),
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )
    candidate = next(row for row in artifact["rows"] if row["strategy_uid"] == "uid-candidate")

    assert candidate["allocation_role"] == "active_unallocated"
    assert candidate["recommended_weight"] <= 0.03
    assert candidate["action"] in {"REVIEW", "ZERO_WEIGHT", "HOLD"}
    assert candidate["rationale"]
    assert "active_unallocated_starter_cap" in candidate["constraints_applied"]


def test_combined_row_is_derived_composite_not_ordinary() -> None:
    artifact = build_daily_allocation_recommendation_artifact(
        Path("."),
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )
    combined = next(row for row in artifact["rows"] if row["strategy_uid"] == "COMBINED_PORTFOLIO")

    assert combined["allocation_role"] == "top_level_derived_composite"
    assert combined["action"] == "HOLD"
    assert "derived_composite_not_ordinary_denominator" in combined["constraints_applied"]


def test_missing_evidence_produces_review_not_fake_confidence() -> None:
    artifact = build_daily_allocation_recommendation_artifact(
        Path("."),
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )
    missing = next(row for row in artifact["rows"] if row["strategy_uid"] == "uid-active-missing")

    assert missing["action"] == "REVIEW"
    assert "Missing ML evidence" in missing["missing_evidence"]
    assert any("missing_ml_penalty" == item for item in missing["constraints_applied"])
    assert "confidence" not in missing
    assert "optimizer" not in missing["rationale"].lower()


def test_target_weights_are_non_negative_and_cash_is_explicit() -> None:
    artifact = build_daily_allocation_recommendation_artifact(
        Path("."),
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    assert all(row["recommended_weight"] >= 0.0 for row in artifact["rows"])
    assert artifact["target_sum"] >= 0.0
    assert artifact["residual_cash_weight"] >= 0.0
    assert abs(artifact["target_sum"] + artifact["residual_cash_weight"] - 1.0) <= artifact["constraints"]["weight_sum_tolerance"]


def test_write_and_read_latest_daily_allocation_recommendation(tmp_path: Path) -> None:
    missing = read_latest_daily_allocation_recommendation(tmp_path)
    assert missing["ok"] is False
    assert missing["status"] == "MISSING_ARTIFACT"

    result = write_daily_allocation_recommendation_artifact(
        tmp_path,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )
    latest = read_latest_daily_allocation_recommendation(tmp_path)

    assert result["status"] == "GENERATED"
    assert result["artifact_path"] == "data/automation/daily_allocation_recommendations/2026-07-01.json"
    assert latest["ok"] is True
    assert latest["artifact"]["financial_state_mutated"] is False
    assert latest["artifact"]["paper_apply_created"] is False
    assert latest["artifact"]["approved_plan_created"] is False


def test_endpoint_generate_writes_only_recommendation_artifact_and_get_is_read_only(tmp_path: Path, monkeypatch) -> None:
    root = _copy_root(tmp_path)
    monkeypatch.setenv("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", str(tmp_path / "missing_alpha_research"))
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    before = _paper_rebalance_hashes(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        missing_status, missing = _fetch_json(
            f"http://127.0.0.1:{port}/api/automation-intelligence/daily-allocation-recommendations/latest"
        )
        before_get = _paper_rebalance_hashes(root)
        status, payload = _post_json(
            f"http://127.0.0.1:{port}/api/automation-intelligence/daily-allocation-recommendations/generate"
        )
        latest_status, latest = _fetch_json(
            f"http://127.0.0.1:{port}/api/automation-intelligence/daily-allocation-recommendations/latest"
        )
        after = _paper_rebalance_hashes(root)

        assert missing_status == 404
        assert missing["status"] == "MISSING_ARTIFACT"
        assert before_get == before
        assert status == 201
        assert payload["financial_state_mutated"] is False
        assert payload["paper_apply_created"] is False
        assert payload["approved_plan_created"] is False
        assert latest_status == 200
        assert latest["artifact"]["source"] == "daily_allocation_recommendation_artifact_v1"
        assert before == after
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
