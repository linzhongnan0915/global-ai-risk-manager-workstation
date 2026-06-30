from __future__ import annotations

import hashlib
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts import run_workstation_server as server_module
from scripts.run_workstation_server import WorkstationHandler


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _hashes(root: Path) -> dict[str, str]:
    names = [
        "approved_rebalance_plans.json",
        "applied_rebalance_events.json",
        "current_paper_target_weights.json",
    ]
    paper_dir = root / "data" / "paper_rebalance"
    return {
        name: hashlib.sha256((paper_dir / name).read_bytes()).hexdigest()
        for name in names
    }


def _root_with_plan(tmp_path: Path) -> Path:
    root = tmp_path / "workstation"
    paper_dir = root / "data" / "paper_rebalance"
    _write_json(
        paper_dir / "approved_rebalance_plans.json",
        {
            "schema_version": "approved_rebalance_plan_v1",
            "plans": [
                {
                    "plan_id": "test-plan-id",
                    "status": "Accepted Pending Application",
                    "target_weights": {"test-strategy-uid": 0.1},
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
        {"schema_version": "approved_rebalance_plan_v1", "weights": {"test-strategy-uid": 0.0}},
    )
    return root


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class _ServerFixture:
    def __init__(self, root: Path):
        self.root = root
        self.original_root = WorkstationHandler.server_root
        self.original_bytes = WorkstationHandler.operational_snapshot_bytes
        self.port = _free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), WorkstationHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        WorkstationHandler.server_root = self.root
        WorkstationHandler.operational_snapshot_bytes = None
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, exc_type, exc, tb):
        self.httpd.shutdown()
        self.httpd.server_close()
        WorkstationHandler.server_root = self.original_root
        WorkstationHandler.operational_snapshot_bytes = self.original_bytes


def test_explicit_apply_without_confirmation_is_rejected_without_mutation(tmp_path, monkeypatch) -> None:
    root = _root_with_plan(tmp_path)
    before = _hashes(root)
    calls: list[str] = []
    monkeypatch.setattr(
        server_module,
        "apply_paper_rebalance_plan",
        lambda server_root, plan_id: calls.append(plan_id) or {"ok": True},
    )

    with _ServerFixture(root) as base:
        status, payload = _post_json(f"{base}/api/paper-rebalance/apply", {"plan_id": "test-plan-id"})

    assert status == 400
    assert payload["paper_apply_gated"] is True
    assert "apply_confirmation" in payload["error"]
    assert calls == []
    assert _hashes(root) == before


def test_explicit_apply_with_wrong_confirmation_text_is_rejected_without_mutation(tmp_path, monkeypatch) -> None:
    root = _root_with_plan(tmp_path)
    before = _hashes(root)
    calls: list[str] = []
    monkeypatch.setattr(
        server_module,
        "apply_paper_rebalance_plan",
        lambda server_root, plan_id: calls.append(plan_id) or {"ok": True},
    )

    with _ServerFixture(root) as base:
        status, payload = _post_json(
            f"{base}/api/paper-rebalance/apply",
            {
                "plan_id": "test-plan-id",
                "apply_confirmation": True,
                "confirmation_text": "WRONG_CONFIRMATION",
            },
        )

    assert status == 400
    assert payload["paper_apply_gated"] is True
    assert "confirmation_text" in payload["error"]
    assert calls == []
    assert _hashes(root) == before


def test_explicit_apply_with_confirmation_reaches_existing_apply_path(tmp_path, monkeypatch) -> None:
    root = _root_with_plan(tmp_path)
    calls: list[tuple[Path, str]] = []

    def fake_apply(server_root: Path, plan_id: str) -> dict:
        calls.append((server_root, plan_id))
        return {
            "ok": True,
            "current_paper_target": {
                "applied_status": "Applied to Paper Allocation",
                "execution_mode": "Paper Only",
                "live_brokerage_fill": "No",
            },
            "cost_record": {"official_ledger_mutation": "No"},
        }

    monkeypatch.setattr(server_module, "apply_paper_rebalance_plan", fake_apply)
    monkeypatch.setattr(WorkstationHandler, "warm_operational_snapshot_cache", classmethod(lambda cls, *args, **kwargs: None))
    monkeypatch.setattr(
        WorkstationHandler,
        "_paper_rebalance_response",
        lambda self, extra=None: {"ok": True, **(extra or {})},
    )

    with _ServerFixture(root) as base:
        status, payload = _post_json(
            f"{base}/api/paper-rebalance/apply",
            {
                "plan_id": "test-plan-id",
                "apply_confirmation": True,
                "confirmation_text": server_module.PAPER_APPLY_CONFIRMATION_TEXT,
            },
        )

    assert status == 200
    assert calls == [(root, "test-plan-id")]
    assert payload["current_paper_target"]["execution_mode"] == "Paper Only"
    assert payload["current_paper_target"]["live_brokerage_fill"] == "No"
