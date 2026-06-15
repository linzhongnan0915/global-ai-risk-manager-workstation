"""Tests for bootstrap artifact splitting and lazy-load API endpoints."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts.run_workstation_server import WorkstationHandler, _json_bytes, ensure_deployment_artifact
from src.market.artifact_bootstrap import (
    build_bootstrap_artifact,
    build_research_extension,
    build_strategy_detail,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _start_server(port: int) -> ThreadingHTTPServer:
    artifact = ensure_deployment_artifact(PROJECT_ROOT)
    WorkstationHandler.warm_artifact_caches(artifact)
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture(scope="module")
def full_artifact() -> dict:
    return ensure_deployment_artifact(PROJECT_ROOT)


def test_bootstrap_artifact_is_smaller_than_full(full_artifact):
    bootstrap = build_bootstrap_artifact(full_artifact)
    full_size = len(_json_bytes(full_artifact))
    bootstrap_size = len(_json_bytes(bootstrap))
    assert bootstrap_size < full_size * 0.35
    assert bootstrap["literature_strategy_backtests"]["lazy_load"] is True
    assert bootstrap["literature_strategy_backtests"]["results"] == []
    assert bootstrap["literature_strategy_backtests"]["results_count"] == len(
        (full_artifact.get("literature_strategy_backtests") or {}).get("results") or []
    )


def test_bootstrap_strategies_omit_drawer_payloads(full_artifact):
    bootstrap = build_bootstrap_artifact(full_artifact)
    assert bootstrap["strategies"]
    for strategy in bootstrap["strategies"]:
        assert "position_packet" not in strategy
        assert "chart_series" not in (strategy.get("risk_packet") or {})


def test_research_extension_restores_literature(full_artifact):
    extension = build_research_extension(full_artifact)
    full_results = (full_artifact.get("literature_strategy_backtests") or {}).get("results") or []
    extension_results = (extension.get("literature_strategy_backtests") or {}).get("results") or []
    assert len(extension_results) == len(full_results)


def test_strategy_detail_endpoint_returns_drawer_payloads(full_artifact):
    strategy_id = full_artifact["strategies"][0]["strategy_id"]
    detail = build_strategy_detail(full_artifact, strategy_id)
    assert detail is not None
    assert detail["strategy_id"] == strategy_id
    assert "position_packet" in detail or "risk_packet" in detail


def test_bootstrap_and_research_http_endpoints():
    port = _free_port()
    server = _start_server(port)
    try:
        full_path = PROJECT_ROOT / "output" / "dashboard_artifact.json"
        full_size = full_path.stat().st_size
        bootstrap_status, _, bootstrap_body = _fetch(f"http://127.0.0.1:{port}/api/artifact/bootstrap")
        assert bootstrap_status == 200
        bootstrap = json.loads(bootstrap_body.decode("utf-8"))
        assert bootstrap["artifact_load_profile"]["mode"] == "bootstrap"
        assert len(bootstrap_body) < full_size * 0.35

        research_status, _, research_body = _fetch(f"http://127.0.0.1:{port}/api/artifact/research")
        assert research_status == 200
        research = json.loads(research_body.decode("utf-8"))
        assert (research.get("literature_strategy_backtests") or {}).get("results")

        strategy_id = bootstrap["strategies"][0]["strategy_id"]
        detail_status, _, detail_body = _fetch(
            f"http://127.0.0.1:{port}/api/artifact/strategy-detail?strategy_id={strategy_id}"
        )
        assert detail_status == 200
        detail = json.loads(detail_body.decode("utf-8"))
        assert detail["ok"] is True
        assert detail["strategy_id"] == strategy_id
    finally:
        server.shutdown()
        server.server_close()
