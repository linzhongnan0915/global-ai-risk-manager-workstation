from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts.run_workstation_server import WorkstationHandler
from src.automation import control_layer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(root: Path) -> tuple[ThreadingHTTPServer, int]:
    port = _free_port()
    WorkstationHandler.server_root = root
    WorkstationHandler.deployment_artifact = None
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _request(port: int, path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None if method == "GET" else json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _paths(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}


def test_build_automation_control_status_missing_artifacts_full_schema(tmp_path: Path):
    before = _paths(tmp_path)
    status = control_layer.build_automation_control_status(tmp_path)
    after = _paths(tmp_path)

    assert before == after
    assert status["ok"] is True
    assert status["status"] == "PARTIAL"
    assert status["daily_cycle"]["status"] == "MISSING_ARTIFACT"
    assert status["daily_recommendation"]["status"] == "MISSING_ARTIFACT"
    assert status["rebalance_proposal"]["status"] == "MISSING_ARTIFACT"
    assert set(status) >= {
        "generated_at",
        "scheduler",
        "manual_review",
        "regime",
    }
    assert status["manual_review"]["silent_auto_apply"] is False
    assert status["manual_review"]["apply_requires_user_approval"] is True
    assert status["regime"]["status"] == "pending"
    assert status["regime"]["schema_ready"] is True
    assert status["regime"]["strategy_regime_fit"] == []


def test_status_helper_is_read_only_and_creates_no_files(tmp_path: Path):
    before = _paths(tmp_path)
    control_layer.build_automation_control_status(tmp_path)
    assert _paths(tmp_path) == before


def test_run_automation_daily_cycle_control_never_auto_applies(tmp_path: Path):
    def runner(root: str | Path, *, force: bool = False):
        return {
            "ok": True,
            "status": "GENERATED",
            "artifact_path": "data/automation/daily_cycle/2099-01-01.json",
            "daily_cycle": {
                "status": "AVAILABLE",
                "as_of_date": "2099-01-01",
                "last_run_at": "2099-01-01T00:00:00+00:00",
                "steps": [{"name": "daily_recommendation"}],
            },
        }

    def daily_allocation_writer(root: str | Path):
        return {
            "ok": True,
            "status": "GENERATED",
            "artifact_path": "data/automation/daily_allocation_recommendations/2099-01-01.json",
            "artifact": {
                "generated_at": "2099-01-01T00:00:00+00:00",
                "recommendation_date": "2099-01-01",
                "rows": [{"strategy": "example"}],
            },
        }

    result = control_layer.run_automation_daily_cycle_control(
        tmp_path,
        force=True,
        runner=runner,
        daily_allocation_writer=daily_allocation_writer,
    )

    assert result["ok"] is True
    assert result["no_auto_apply"] is True
    assert result["approved_plan_created"] is False
    assert result["applied_event_created"] is False
    assert result["daily_recommendation"]["row_count"] == 1
    assert result["manual_review"]["apply_requires_user_approval"] is True
    assert result["regime"]["schema_ready"] is True


def test_generate_rebalance_proposal_control_review_only(tmp_path: Path):
    def writer(root: str | Path):
        return {
            "ok": True,
            "status": "GENERATED",
            "artifact_path": "data/automation/biweekly_rebalance_proposals/2099-01-01.json",
            "artifact": {
                "generated_at": "2099-01-01T00:00:00+00:00",
                "proposal_date": "2099-01-01",
                "proposal_rows": [{"strategy": "example"}],
            },
        }

    result = control_layer.generate_rebalance_proposal_control(tmp_path, writer=writer)

    assert result["ok"] is True
    assert result["paper_only"] is True
    assert result["requires_manual_approval"] is True
    assert result["no_auto_apply"] is True
    assert result["approved_plan_created"] is False
    assert result["applied_event_created"] is False
    assert result["rebalance_proposal"]["row_count"] == 1
    assert result["regime"]["status"] == "pending"


def test_generate_rebalance_proposal_control_uses_paper_fallback(tmp_path: Path):
    def primary(root: str | Path):
        return {"ok": False, "status": "MISSING_INPUT"}

    def fallback(root: str | Path):
        return {
            "ok": True,
            "status": "GENERATED",
            "artifact_path": "data/automation/paper_allocation_proposals/2099-01-01.json",
            "artifact": {"as_of_date": "2099-01-01", "rows": [{"strategy": "example"}]},
        }

    result = control_layer.generate_rebalance_proposal_control(tmp_path, writer=primary, fallback_writer=fallback)

    assert result["ok"] is True
    assert result["control"]["proposal_type"] == "paper_allocation_proposal_fallback"
    assert result["requires_manual_approval"] is True


def test_server_exposes_automation_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "scripts.run_workstation_server.build_automation_control_status",
        lambda root: {"ok": True, "status": "PARTIAL", "manual_review": control_layer.manual_review_schema(), "regime": control_layer.regime_schema()},
    )
    server, port = _start_server(tmp_path)
    try:
        status, payload = _request(port, "/api/automation/status")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert payload["ok"] is True
    assert payload["manual_review"]["silent_auto_apply"] is False


def test_server_exposes_run_daily_cycle_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "scripts.run_workstation_server.run_automation_daily_cycle_control",
        lambda root, *, force=False: {
            "ok": True,
            "status": "GENERATED",
            "daily_cycle": {"status": "AVAILABLE"},
            "manual_review": control_layer.manual_review_schema(),
            "regime": control_layer.regime_schema(),
            "no_auto_apply": True,
            "approved_plan_created": False,
            "applied_event_created": False,
        },
    )
    server, port = _start_server(tmp_path)
    try:
        status, payload = _request(port, "/api/automation/run-daily-cycle", method="POST", payload={"force": True})
    finally:
        server.shutdown()
        server.server_close()

    assert status == 201
    assert payload["no_auto_apply"] is True
    assert payload["approved_plan_created"] is False
    assert payload["applied_event_created"] is False


def test_server_exposes_generate_rebalance_proposal_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "scripts.run_workstation_server.generate_rebalance_proposal_control",
        lambda root: {
            "ok": True,
            "status": "GENERATED",
            "rebalance_proposal": {"status": "GENERATED"},
            "paper_only": True,
            "requires_manual_approval": True,
            "no_auto_apply": True,
            "approved_plan_created": False,
            "applied_event_created": False,
            "regime": control_layer.regime_schema(),
        },
    )
    server, port = _start_server(tmp_path)
    try:
        status, payload = _request(port, "/api/automation/generate-rebalance-proposal", method="POST", payload={})
    finally:
        server.shutdown()
        server.server_close()

    assert status == 201
    assert payload["requires_manual_approval"] is True
    assert payload["approved_plan_created"] is False
    assert payload["applied_event_created"] is False
