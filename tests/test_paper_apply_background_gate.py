from __future__ import annotations

import hashlib
import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts import run_workstation_server as server_module
from scripts.run_workstation_server import WorkstationHandler


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _hashes(root: Path) -> dict[str, str]:
    paper_dir = root / "data" / "paper_rebalance"
    names = [
        "approved_rebalance_plans.json",
        "applied_rebalance_events.json",
        "current_paper_target_weights.json",
    ]
    return {
        name: hashlib.sha256((paper_dir / name).read_bytes()).hexdigest()
        for name in names
    }


def _root_with_due_plan(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "workstation"
    uid = "test-paper-strategy-uid"
    paper_dir = root / "data" / "paper_rebalance"
    _write_json(
        paper_dir / "approved_rebalance_plans.json",
        {
            "schema_version": "approved_rebalance_plan_v1",
            "plans": [
                {
                    "schema_version": "approved_rebalance_plan_v1",
                    "plan_id": "test-approved-plan",
                    "status": "APPROVED_WAITING_EFFECTIVE_DATE",
                    "effective_date": "2026-06-30",
                    "portfolio_nav_used_for_cost_estimate": 1000000.0,
                    "rows": [
                        {
                            "strategy_uid": uid,
                            "approved_target_weight": 0.25,
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        paper_dir / "applied_rebalance_events.json",
        {"schema_version": "applied_rebalance_events_v1", "events": []},
    )
    _write_json(
        paper_dir / "current_paper_target_weights.json",
        {"schema_version": "approved_rebalance_plan_v1", "weights": {uid: 0.2}},
    )
    snapshot = {
        "session_state": {
            "current_intraday_session": "2026-06-30",
            "last_trading_session": "2026-06-30",
            "calendar_date": "2026-06-30",
        },
        "portfolio_summary": {"nav": 1000000.0},
        "strategies": [
            {
                "strategy_uid": uid,
                "membership_state": "executed",
                "current_operational_status": "ACTIVE_PAPER",
                "current_weight": 0.2,
            }
        ],
    }
    return root, snapshot


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _post_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_background_scheduler_apply_is_gated_by_default_and_preserves_canonical_files(tmp_path, monkeypatch) -> None:
    root, snapshot = _root_with_due_plan(tmp_path)
    before = _hashes(root)
    monkeypatch.delenv(server_module.BACKGROUND_PAPER_APPLY_ENV, raising=False)

    result = server_module.background_paper_rebalance_apply_check(root, snapshot=snapshot)

    assert result["background_apply_enabled"] is False
    assert result["background_apply_gated"] is True
    assert result["status"] == "BACKGROUND_APPLY_GATED"
    assert result["applied"] is False
    assert result["attempted"] is False
    assert _hashes(root) == before
    events = json.loads((root / "data/paper_rebalance/applied_rebalance_events.json").read_text(encoding="utf-8"))
    assert not any(event.get("applied_status") == "APPLIED_PAPER" or event.get("event_id") for event in events["events"])


def test_background_scheduler_apply_delegates_only_when_env_flag_is_enabled(tmp_path, monkeypatch) -> None:
    root, snapshot = _root_with_due_plan(tmp_path)
    calls: list[tuple[Path, dict]] = []

    def fake_apply(path: Path, *, snapshot: dict) -> dict:
        calls.append((path, snapshot))
        return {"attempted": True, "applied": True, "plan_id": "delegated-test-plan"}

    monkeypatch.setenv(server_module.BACKGROUND_PAPER_APPLY_ENV, "1")
    monkeypatch.setattr(server_module, "apply_due_approved_rebalance_plan", fake_apply)

    result = server_module.background_paper_rebalance_apply_check(root, snapshot=snapshot)

    assert result["background_apply_enabled"] is True
    assert result["background_apply_gated"] is False
    assert result["applied"] is True
    assert calls == [(root, snapshot)]


def test_paper_allocation_proposal_and_report_endpoints_are_review_only(tmp_path, monkeypatch) -> None:
    root, _snapshot = _root_with_due_plan(tmp_path)
    (root / "dashboard/data").mkdir(parents=True, exist_ok=True)
    before = _hashes(root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.operational_snapshot_bytes = None
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(
            server_module,
            "write_paper_allocation_proposal",
            lambda server_root: {"ok": True, "financial_state_mutated": False, "paper_apply_created": False},
        )
        monkeypatch.setattr(
            server_module,
            "write_paper_allocation_report",
            lambda server_root, rows, source_proposal_artifact=None, draft_summary=None: {
                "ok": True,
                "financial_state_mutated": False,
                "paper_apply_created": False,
                "approved_plan_created": False,
            },
        )
        base = f"http://127.0.0.1:{port}"
        proposal_status, proposal = _post_json(f"{base}/api/automation-intelligence/paper-allocation-proposal/generate")
        report_status, report = _post_json(
            f"{base}/api/automation-intelligence/paper-allocation-report/generate",
            {"rows": [], "draft_summary": {}},
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes

    assert proposal_status == 201
    assert report_status == 201
    assert proposal["paper_apply_created"] is False
    assert report["paper_apply_created"] is False
    assert report["approved_plan_created"] is False
    assert _hashes(root) == before
