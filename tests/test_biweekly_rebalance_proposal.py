import hashlib
import json
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler
from src.automation.biweekly_rebalance_proposal import (
    build_biweekly_rebalance_proposal_artifact,
    read_latest_biweekly_rebalance_proposal,
    write_biweekly_rebalance_proposal_artifact,
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


def _daily_artifact() -> dict:
    return {
        "ok": True,
        "source": "daily_allocation_recommendation_artifact_v1",
        "schema_version": "daily_allocation_recommendation_v1",
        "generated_at": "2026-07-01T00:00:00+00:00",
        "recommendation_date": "2026-07-01",
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "rows": [
            {
                "strategy_uid": "uid-active-alpha",
                "strategy_id": "alpha-1",
                "internal_id": "internal-active-alpha",
                "strategy_name": "Display Only Alpha",
                "allocation_role": "ordinary_active",
                "current_weight": 0.10,
                "recommended_weight": 0.12,
                "delta": 0.02,
                "action": "INCREASE",
                "rationale": "daily recommendation test row",
                "evidence_status": "STRONG",
                "risk_status": "ok",
                "ml_status": "ML_EVIDENCE_AVAILABLE",
                "attribution_status": "Attribution Available",
                "missing_evidence": [],
                "constraints_applied": ["daily_constraint"],
                "source_artifacts": [{"kind": "daily", "path": "test-only/daily.json"}],
                "paper_state": {"paper_shadow_only": True},
                "live_trading": False,
                "brokerage_execution": False,
            },
            {
                "strategy_uid": "uid-active-missing",
                "internal_id": "internal-active-missing",
                "strategy_name": "Display Missing",
                "allocation_role": "ordinary_active",
                "current_weight": 0.08,
                "recommended_weight": 0.09,
                "delta": 0.01,
                "action": "REVIEW",
                "rationale": "missing evidence review",
                "evidence_status": "PARTIAL",
                "risk_status": "MISSING_RISK_EVIDENCE",
                "ml_status": "ML_MISSING_EVIDENCE",
                "attribution_status": "Missing Attribution Evidence",
                "missing_evidence": ["Missing ML evidence", "Missing Attribution Evidence"],
                "constraints_applied": ["missing_ml_penalty"],
                "source_artifacts": [],
                "paper_state": {"paper_shadow_only": True},
                "live_trading": False,
                "brokerage_execution": False,
            },
            {
                "strategy_uid": "uid-candidate",
                "strategy_id": "candidate-123",
                "strategy_name": "Candidate Display",
                "allocation_role": "active_unallocated",
                "current_weight": 0.0,
                "recommended_weight": 0.02,
                "delta": 0.02,
                "action": "INCREASE",
                "rationale": "starter cap",
                "evidence_status": "STRONG",
                "risk_status": "watch",
                "ml_status": "ML_EVIDENCE_AVAILABLE",
                "attribution_status": "Attribution Available",
                "missing_evidence": [],
                "constraints_applied": ["active_unallocated_starter_cap"],
                "source_artifacts": [{"kind": "activation", "path": "test-only/candidate.json"}],
                "paper_state": {"paper_shadow_only": True},
                "live_trading": False,
                "brokerage_execution": False,
            },
            {
                "strategy_uid": "COMBINED_PORTFOLIO",
                "internal_id": "COMBINED_PORTFOLIO",
                "strategy_name": "Combined Portfolio",
                "allocation_role": "top_level_derived_composite",
                "current_weight": 1.0,
                "recommended_weight": 1.0,
                "delta": 0.0,
                "action": "HOLD",
                "rationale": "derived context",
                "evidence_status": "PARTIAL",
                "risk_status": "ok",
                "ml_status": "ML_EVIDENCE_AVAILABLE",
                "attribution_status": "Attribution Available",
                "missing_evidence": [],
                "constraints_applied": ["derived_composite_not_ordinary_denominator"],
                "source_artifacts": [],
                "paper_state": {"paper_shadow_only": True},
                "live_trading": False,
                "brokerage_execution": False,
            },
            {
                "strategy_uid": "uid-excluded",
                "strategy_name": "Excluded Display",
                "allocation_role": "excluded_or_review",
                "current_weight": 0.03,
                "recommended_weight": 0.0,
                "delta": -0.03,
                "action": "ZERO_WEIGHT",
                "rationale": "excluded",
                "evidence_status": "WEAK",
                "risk_status": "MISSING_RISK_EVIDENCE",
                "ml_status": "ML_MISSING_EVIDENCE",
                "attribution_status": "Missing Attribution Evidence",
                "missing_evidence": [],
                "constraints_applied": ["excluded_or_review"],
                "source_artifacts": [],
                "paper_state": {"paper_shadow_only": True},
                "live_trading": False,
                "brokerage_execution": False,
            },
        ],
    }


def _write_daily(root: Path, name: str, artifact: dict | None = None) -> Path:
    path = root / "data/automation/daily_allocation_recommendations" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact or _daily_artifact(), indent=2), encoding="utf-8")
    return path


def _rows_by_uid(artifact: dict) -> dict[str, dict]:
    return {row["strategy_uid"]: row for row in artifact["rows"]}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_json(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _paper_rebalance_hashes(root: Path) -> dict[str, str]:
    base = root / "data/paper_rebalance"
    if not base.exists():
        return {}
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(base.glob("**/*.json"))}


def test_missing_daily_allocation_returns_missing_and_creates_no_fake_proposal(tmp_path: Path) -> None:
    result = write_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 1, tzinfo=timezone.utc))

    assert result["ok"] is False
    assert result["status"] == "MISSING_DAILY_ALLOCATION_RECOMMENDATION"
    assert not (tmp_path / "data/automation/biweekly_rebalance_proposals").exists()


def test_generated_proposal_uses_latest_daily_allocation_artifact(tmp_path: Path) -> None:
    old = _daily_artifact()
    old["recommendation_date"] = "2026-06-30"
    old["rows"][0]["recommended_weight"] = 0.11
    _write_daily(tmp_path, "2026-06-30.json", old)
    _write_daily(tmp_path, "2026-07-01.json", _daily_artifact())

    artifact = build_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))

    assert artifact["source_daily_allocation_recommendation"]["recommendation_date"] == "2026-07-01"
    assert artifact["input_artifacts"]["daily_allocation_recommendation"].endswith("2026-07-01.json")
    assert _rows_by_uid(artifact)["uid-active-alpha"]["recommended_weight"] == 0.12


def test_every_daily_allocation_row_appears_with_explicit_weight_fields(tmp_path: Path) -> None:
    daily = _daily_artifact()
    _write_daily(tmp_path, "2026-07-01.json", daily)
    artifact = build_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))
    rows = _rows_by_uid(artifact)

    assert set(rows) == {row["strategy_uid"] for row in daily["rows"]}
    for row in rows.values():
        assert {"current_weight", "recommended_weight", "proposed_weight", "delta", "drift"} <= set(row)
        assert row["proposed_weight"] is not None


def test_turnover_and_estimated_transaction_cost_are_computed(tmp_path: Path) -> None:
    _write_daily(tmp_path, "2026-07-01.json")
    artifact = build_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))
    active = _rows_by_uid(artifact)["uid-active-alpha"]

    assert active["estimated_turnover"] == abs(active["proposed_weight"] - active["current_weight"])
    assert active["estimated_transaction_cost_bps"] == 5.0
    assert active["estimated_transaction_cost_weight"] == active["estimated_turnover"] * 5.0 / 10000.0


def test_combined_row_is_context_derived_not_tradeable_ordinary_row(tmp_path: Path) -> None:
    _write_daily(tmp_path, "2026-07-01.json")
    artifact = build_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))
    combined = _rows_by_uid(artifact)["COMBINED_PORTFOLIO"]

    assert combined["allocation_role"] == "top_level_derived_composite"
    assert combined["proposal_action"] == "REVIEW_ONLY"
    assert combined["proposed_weight"] == combined["current_weight"]
    assert "derived_composite_context_not_tradeable" in combined["constraints_applied"]


def test_active_unallocated_row_is_starter_or_review_with_explicit_reason(tmp_path: Path) -> None:
    _write_daily(tmp_path, "2026-07-01.json")
    artifact = build_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))
    candidate = _rows_by_uid(artifact)["uid-candidate"]

    assert candidate["allocation_role"] == "active_unallocated"
    assert candidate["proposal_action"] in {"BUY_INCREASE", "REVIEW_ONLY"}
    assert candidate["proposed_weight"] <= 0.02
    assert candidate["rationale"]


def test_missing_evidence_propagates_to_review_only(tmp_path: Path) -> None:
    _write_daily(tmp_path, "2026-07-01.json")
    artifact = build_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))
    missing = _rows_by_uid(artifact)["uid-active-missing"]

    assert missing["proposal_action"] == "REVIEW_ONLY"
    assert missing["proposed_weight"] == missing["current_weight"]
    assert "Missing ML evidence" in missing["missing_evidence"]


def test_write_and_read_latest_are_proposal_only_and_safe(tmp_path: Path) -> None:
    _write_daily(tmp_path, "2026-07-01.json")
    before_get = read_latest_biweekly_rebalance_proposal(tmp_path)
    result = write_biweekly_rebalance_proposal_artifact(tmp_path, now=datetime(2026, 7, 2, tzinfo=timezone.utc))
    latest = read_latest_biweekly_rebalance_proposal(tmp_path)

    assert before_get["status"] == "MISSING_ARTIFACT"
    assert result["status"] == "GENERATED"
    assert result["artifact_path"] == "data/automation/biweekly_rebalance_proposals/2026-07-02.json"
    assert latest["ok"] is True
    assert latest["artifact"]["proposal_only"] is True
    assert latest["artifact"]["financial_state_mutated"] is False
    assert latest["artifact"]["paper_apply_created"] is False
    assert latest["artifact"]["approved_plan_created"] is False


def test_endpoint_get_read_only_and_post_writes_only_proposal_artifact(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    _write_daily(root, "2026-07-01.json")
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    before_paper = _paper_rebalance_hashes(root)
    port = _free_port()
    server = threading.Thread
    httpd = None
    try:
        from http.server import ThreadingHTTPServer

        httpd = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
        server = threading.Thread(target=httpd.serve_forever, daemon=True)
        server.start()
        get_status, get_payload = _fetch_json(
            f"http://127.0.0.1:{port}/api/automation-intelligence/biweekly-rebalance-proposal/latest"
        )
        before_after_get = _paper_rebalance_hashes(root)
        post_status, post_payload = _post_json(
            f"http://127.0.0.1:{port}/api/automation-intelligence/biweekly-rebalance-proposal/generate"
        )
        latest_status, latest = _fetch_json(
            f"http://127.0.0.1:{port}/api/automation-intelligence/biweekly-rebalance-proposal/latest"
        )
        after_paper = _paper_rebalance_hashes(root)

        assert get_status == 404
        assert get_payload["status"] == "MISSING_ARTIFACT"
        assert before_after_get == before_paper
        assert post_status == 201
        assert post_payload["financial_state_mutated"] is False
        assert post_payload["paper_apply_created"] is False
        assert post_payload["approved_plan_created"] is False
        assert latest_status == 200
        assert latest["artifact"]["source"] == "biweekly_paper_rebalance_proposal_v1"
        assert before_paper == after_paper
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes


def test_post_generate_missing_daily_does_not_create_paper_or_approved_plan(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    before_paper = _paper_rebalance_hashes(root)
    result = write_biweekly_rebalance_proposal_artifact(root, now=datetime(2026, 7, 2, tzinfo=timezone.utc))

    assert result["status"] == "MISSING_DAILY_ALLOCATION_RECOMMENDATION"
    assert _paper_rebalance_hashes(root) == before_paper
    assert not (root / "data/automation/biweekly_rebalance_proposals").exists()
