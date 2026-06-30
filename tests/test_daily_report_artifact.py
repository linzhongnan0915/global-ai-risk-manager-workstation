from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.run_workstation_server import WorkstationHandler
from src.automation.daily_report import (
    build_daily_report_artifact,
    read_latest_daily_report_artifact,
    write_daily_report_artifact,
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


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def _paper_hashes(root: Path) -> dict[str, str]:
    folder = root / "data/paper_rebalance"
    return {str(path.relative_to(root)): _file_hash(path) for path in sorted(folder.glob("*.json"))}


def _write_paper_files(root: Path) -> None:
    folder = root / "data/paper_rebalance"
    folder.mkdir(parents=True, exist_ok=True)
    for name in (
        "current_paper_target_weights.json",
        "paper_rebalance_plans.json",
        "paper_rebalance_costs.json",
        "approved_rebalance_plans.json",
        "monthly_rebalance_proposals.json",
    ):
        (folder / name).write_text(json.dumps({"test_fixture": name}), encoding="utf-8")


def _write_risk_evidence(root: Path) -> Path:
    path = root / "data/automation/risk_evidence/20260630T000000.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = [
        "Prototype Only",
        "Paper Only",
        "Institutional Validation Pending",
        "Missing Risk Evidence",
        "Insufficient Risk History",
    ]
    payload = {
        "ok": True,
        "source": "risk_evidence_artifact_v0",
        "schema_version": "0.1.0",
        "generated_at": "2026-06-30T00:00:00+00:00",
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "observation_count": 5,
        "window_start": "2026-06-04",
        "window_end": "2026-06-11",
        "portfolio_risk_evidence": {
            "status": "PARTIAL",
            "risk_metrics": {
                "historical_var_95": {"status": "INSUFFICIENT_HISTORY", "value": None},
                "historical_cvar_95": {"status": "INSUFFICIENT_HISTORY", "value": None},
                "max_drawdown": {"status": "COMPUTED", "value": -0.02},
                "realized_volatility": {"status": "COMPUTED", "value": 0.01},
            },
            "labels": labels,
        },
        "strategy_risk_evidence": [],
        "missing_data": [
            {
                "scope": "portfolio_tail_metrics",
                "status": "INSUFFICIENT_HISTORY",
                "missing_reason": "5 observations found; 20 are required for historical VaR/CVaR.",
            }
        ],
        "labels": labels,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _free_port() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), WorkstationHandler)
    port = int(server.server_address[1])
    server.server_close()
    return port


def _fetch_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_json(url: str) -> tuple[int, dict]:
    request = Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_read_latest_daily_report_missing_artifact(tmp_path: Path) -> None:
    result = read_latest_daily_report_artifact(tmp_path)

    assert result["ok"] is False
    assert result["status"] == "MISSING_ARTIFACT"
    assert result["financial_state_mutated"] is False


def test_generated_daily_report_includes_required_sections(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    _write_risk_evidence(root)

    artifact = build_daily_report_artifact(root, now=datetime(2026, 6, 30, tzinfo=timezone.utc))

    assert artifact["source"] == "daily_report_artifact_v0"
    assert artifact["schema_version"]
    assert artifact["paper_shadow_only"] is True
    assert artifact["financial_state_mutated"] is False
    for key in (
        "input_artifacts",
        "portfolio_summary",
        "allocation_summary",
        "strategy_factory_summary",
        "strategy_intelligence_summary",
        "risk_evidence_summary",
        "daily_actions",
        "missing_evidence",
        "warnings",
        "next_actions",
        "labels",
    ):
        assert key in artifact


def test_daily_report_reports_risk_evidence_status_honestly(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    _write_risk_evidence(root)

    artifact = build_daily_report_artifact(root)
    risk = artifact["risk_evidence_summary"]

    assert risk["var_status"] == "INSUFFICIENT_HISTORY"
    assert risk["cvar_status"] == "INSUFFICIENT_HISTORY"
    assert risk["drawdown_stress_status"] == "COMPUTED"
    assert risk["realized_volatility_status"] == "COMPUTED"
    assert "Risk evidence exists, but VaR/CVaR have insufficient history." in artifact["warnings"]


def test_daily_report_includes_strategy_intelligence_missing_evidence_labels(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)

    artifact = build_daily_report_artifact(root)
    missing = artifact["strategy_intelligence_summary"]["missing_evidence_counts"]

    assert missing["Missing ML Evidence"] > 0
    assert missing["Missing Attribution"] > 0
    assert any(row["status"] == "Missing ML Evidence" for row in artifact["missing_evidence"])
    assert any(row["status"] == "Missing Attribution" for row in artifact["missing_evidence"])


def test_daily_report_generation_does_not_mutate_canonical_paper_files(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    _write_paper_files(root)
    before = _paper_hashes(root)

    result = write_daily_report_artifact(root, now=datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc))
    after = _paper_hashes(root)

    assert result["financial_state_mutated"] is False
    assert result["paper_apply_created"] is False
    assert result["approved_plan_created"] is False
    assert before == after


def test_daily_report_latest_endpoint_is_read_only(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    _write_paper_files(root)
    before = _paper_hashes(root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.operational_snapshot_bytes = None
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/daily-report/latest")
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes

    assert status == 404
    assert payload["status"] == "MISSING_ARTIFACT"
    assert before == _paper_hashes(root)


def test_daily_report_generate_endpoint_review_only_flags(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    _write_risk_evidence(root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.operational_snapshot_bytes = None
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, generated = _post_json(f"http://127.0.0.1:{port}/api/automation-intelligence/daily-report/generate")
        latest_status, latest = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/daily-report/latest")
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes

    assert status == 201
    assert generated["financial_state_mutated"] is False
    assert generated["paper_apply_created"] is False
    assert generated["approved_plan_created"] is False
    assert latest_status == 200
    assert latest["artifact"]["source"] == "daily_report_artifact_v0"
