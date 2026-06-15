"""Deployment readiness tests for workstation server and artifact seed."""

from __future__ import annotations

import gzip
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_workstation_server import (
    WorkstationHandler,
    ensure_deployment_artifact,
    resolve_server_bind,
)
from scripts.validate_deployment_artifact import DeploymentArtifactError, validate_deployment_artifact


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> ThreadingHTTPServer:
    validate_deployment_artifact()
    WorkstationHandler.deployment_artifact = json.loads(
        (PROJECT_ROOT / "output" / "dashboard_artifact.json").read_text(encoding="utf-8")
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _fetch(url: str, *, headers: dict[str, str] | None = None, method: str = "GET", data: bytes = b"{}") -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data if method != "GET" else None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, response_headers, body
    except urllib.error.HTTPError as exc:
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, response_headers, body


def test_resolve_server_bind_defaults(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    host, port = resolve_server_bind()
    assert host == "127.0.0.1"
    assert port == 8765


def test_resolve_server_bind_env(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9999")
    host, port = resolve_server_bind()
    assert host == "0.0.0.0"
    assert port == 9999


def test_validate_deployment_artifact_passes():
    artifact = validate_deployment_artifact()
    assert len(artifact["strategies"]) == 20
    assert artifact["literature_strategy_backtests"]["results"]


def test_missing_artifact_startup_failure(tmp_path: Path):
    missing = tmp_path / "output" / "dashboard_artifact.json"
    with pytest.raises(SystemExit, match="Startup blocked"):
        ensure_deployment_artifact(tmp_path)


def test_validate_deployment_artifact_script_passes():
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_deployment_artifact.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout.lower()


def test_health_endpoint():
    port = _free_port()
    server = _start_server(port)
    try:
        status, headers, body = _fetch(f"http://127.0.0.1:{port}/api/health")
        assert status == 200
        payload = json.loads(body.decode("utf-8"))
        assert payload["status"] == "ok"
        assert int(headers["content-length"]) == len(body)
    finally:
        server.shutdown()
        server.server_close()


def test_gzip_json_and_static_responses():
    port = _free_port()
    server = _start_server(port)
    headers = {"Accept-Encoding": "gzip"}
    try:
        for path in ("/dashboard/app.js", "/output/dashboard_artifact.json"):
            status, response_headers, body = _fetch(f"http://127.0.0.1:{port}{path}", headers=headers)
            assert status == 200
            assert response_headers.get("content-encoding") == "gzip"
            raw = gzip.decompress(body)
            assert len(raw) > 0
            assert int(response_headers["content-length"]) == len(body)
            assert len(body) < len(raw)
        status, _, body = _fetch(f"http://127.0.0.1:{port}/api/health", headers=headers)
        assert status == 200
        assert json.loads(body.decode("utf-8"))["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()


def test_api_errors_do_not_expose_tracebacks():
    port = _free_port()
    server = _start_server(port)
    original = WorkstationHandler._load_artifact

    def _boom(_self):
        raise RuntimeError("secret internal failure")

    WorkstationHandler._load_artifact = _boom  # type: ignore[method-assign]
    try:
        status, _, body = _fetch(
            f"http://127.0.0.1:{port}/api/live-summary",
            headers={"Accept-Encoding": "identity"},
        )
        assert status == 500
        text = body.decode("utf-8")
        assert "trace" not in text.lower()
        assert "secret internal failure" not in text
        payload = json.loads(text)
        assert payload["ok"] is False
    finally:
        WorkstationHandler._load_artifact = original
        server.shutdown()
        server.server_close()


def test_manual_refresh_cooldown():
    port = _free_port()
    server = _start_server(port)
    WorkstationHandler.last_manual_refresh_at = 0.0
    try:
        first_status, _, _ = _fetch(
            f"http://127.0.0.1:{port}/api/refresh",
            headers={"Accept-Encoding": "identity", "Content-Type": "application/json"},
            method="POST",
            data=b"{}",
        )
        assert first_status in {200, 409, 500}
        second_status, _, second_body = _fetch(
            f"http://127.0.0.1:{port}/api/refresh",
            headers={"Accept-Encoding": "identity", "Content-Type": "application/json"},
            method="POST",
            data=b"{}",
        )
        assert second_status == 429
        payload = json.loads(second_body.decode("utf-8"))
        assert payload["ok"] is False
        assert payload["retry_after_seconds"] >= 1
    finally:
        WorkstationHandler.last_manual_refresh_at = 0.0
        server.shutdown()
        server.server_close()


def test_refresh_status_includes_demo_scheduler_label(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    monkeypatch.delenv("ENABLE_INTRADAY_SCHEDULER", raising=False)
    from src.market.intraday_refresh_service import build_refresh_status_payload

    payload = build_refresh_status_payload()
    assert payload["demo_hosting"] is True
    assert payload["scheduler_enabled"] is False
    assert payload["scheduler_label"] == "Manual refresh only while service is running"


def test_invalid_artifact_rejected(tmp_path: Path):
    bad_path = tmp_path / "dashboard_artifact.json"
    bad_path.write_text(json.dumps({"strategies": []}), encoding="utf-8")
    with pytest.raises(DeploymentArtifactError):
        validate_deployment_artifact(bad_path)
