"""HTTP contract tests for the workstation server."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, headers, body


def _fetch_no_redirect(url: str) -> tuple[int, dict[str, str], bytes]:
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirectHandler)
    request = urllib.request.Request(url)
    try:
        with opener.open(request, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, headers, body


def test_resolve_static_path_blocks_traversal():
    handler = WorkstationHandler.__new__(WorkstationHandler)
    handler.server_root = Path(__file__).resolve().parents[1]

    blocked = handler._resolve_static_path("/../output/dashboard_artifact.json")
    assert blocked is None

    allowed = handler._resolve_static_path("/dashboard/index.html")
    assert allowed is not None
    assert allowed.name == "index.html"

    root = handler._resolve_static_path("/")
    assert root is None


def test_root_redirect_and_dashboard_assets():
    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        status, headers, body = _fetch_no_redirect(f"{base}/")
        assert status == 302
        assert headers.get("location") == "/dashboard/index.html"
        assert headers.get("content-length") == "0"
        assert body == b""

        status, headers, body = _fetch(f"{base}/dashboard/index.html")
        assert status == 200
        assert int(headers["content-length"]) == len(body)
        assert b"<!doctype html" in body.lower()

        for asset in (
            "/dashboard/foundation.css",
            "/dashboard/foundation-components.js",
            "/dashboard/foundation-app.js",
            "/dashboard/data/canonical_operational.json",
        ):
            asset_status, asset_headers, asset_body = _fetch(f"{base}{asset}")
            assert asset_status == 200
            assert int(asset_headers["content-length"]) == len(asset_body)
            assert len(asset_body) > 0
    finally:
        server.shutdown()
        server.server_close()


def test_health_and_refresh_status_content_length():
    port = _free_port()
    server = _start_server(port)
    try:
        for path in ("/api/health", "/api/refresh/status"):
            status, headers, body = _fetch(f"http://127.0.0.1:{port}{path}")
            assert status == 200
            assert int(headers["content-length"]) == len(body)
            payload = json.loads(body.decode("utf-8"))
            if path.endswith("/health"):
                assert payload["status"] == "ok"
            else:
                assert "market_status" in payload or "canonical_data_state" in payload
    finally:
        server.shutdown()
        server.server_close()


def test_static_dashboard_written_once():
    port = _free_port()
    server = _start_server(port)
    try:
        status, headers, body = _fetch(f"http://127.0.0.1:{port}/dashboard/index.html")
        assert status == 200
        assert int(headers["content-length"]) == len(body)
        assert b"<!doctype html" in body.lower()
        assert body.count(b"<!doctype html") == 1
    finally:
        server.shutdown()
        server.server_close()
