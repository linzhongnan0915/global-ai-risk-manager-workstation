"""HTTP contract tests for the workstation server."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler
from src.market.artifact_contract import artifact_contract, ensure_dashboard_artifact, validate_runtime_bootstrap_artifact
from src.strategies.strategy_factory_artifact_adapter import load_alpha_snapshot
from src.strategies.strategy_factory_plugin import PROTOTYPE_STRATEGY_ID, list_candidates

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> ThreadingHTTPServer:
    WorkstationHandler.warm_operational_snapshot_cache(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _copy_canonical_root(tmp_path: Path) -> Path:
    root = tmp_path / "workstation"
    (root / "dashboard/data").mkdir(parents=True)
    (root / "dashboard/data/canonical_operational.json").write_text(
        (ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def _create_alpha_research_root(tmp_path: Path) -> Path:
    alpha = tmp_path / "alpha_research"
    for directory in (
        alpha / "strategy_factory_workbench/workbench_data/uploads",
        alpha / "strategy_factory_workbench/workbench_data/upload_batches",
        alpha / "strategy_factory_workbench/workbench_data/material_text",
        alpha / "strategy_factory_workbench/workbench_data/material_analysis",
        alpha / "strategy_factory_workbench/workbench_data/run_plans",
        alpha / "strategy_factory/research_cards",
        alpha / "strategy_factory/codex_test_specs",
        alpha / "strategy_factory/experiments",
        alpha / "strategy_factory/evidence_reports",
        alpha / "experiments",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (alpha / "strategy_factory_workbench/workbench_data/candidate_idea_registry.json").write_text("[]\n", encoding="utf-8")
    (alpha / "strategy_factory_workbench/workbench_data/intake_items.json").write_text("[]\n", encoding="utf-8")
    return alpha


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


def _post_json(url: str, payload: bytes = b"{}") -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, headers, body


def _post_bytes(url: str, payload: bytes, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, response_headers, body
    except urllib.error.HTTPError as exc:
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, response_headers, body


def _advance_factory_to(base: str, target_stage: str) -> dict:
    payload: dict = {}
    for _ in range(12):
        status, _, body = _post_json(f"{base}/api/strategy-factory/run")
        payload = json.loads(body.decode("utf-8"))
        assert status == 201
        if payload["run"]["stage"] == target_stage:
            return payload
    raise AssertionError(f"Strategy Factory did not reach {target_stage}; last payload={payload}")


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


def test_universe_api_endpoints_are_read_only_and_available():
    port = _free_port()
    server = _start_server(port)
    try:
        for path in ("/api/universe/summary", "/api/universe/snapshot", "/api/universe/quality"):
            status, headers, body = _fetch(f"http://127.0.0.1:{port}{path}")
            assert status == 200
            assert int(headers["content-length"]) == len(body)
            payload = json.loads(body.decode("utf-8"))
            assert payload["schema_version"].startswith("universe_")
            assert payload.get("point_in_time_status", "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL")

        status, _, body = _fetch(f"http://127.0.0.1:{port}/api/universe/members?universe=US_LARGE_CAP_CORE")
        payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert payload["ok"] is True
        assert payload["universe_name"] == "US_LARGE_CAP_CORE"
        assert payload["point_in_time_status"] == "CURRENT_MEMBERSHIP_ONLY_PROVISIONAL"

        status, _, body = _fetch(f"http://127.0.0.1:{port}/api/universe/members")
        payload = json.loads(body.decode("utf-8"))
        assert status == 400
        assert payload["ok"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_strategy_factory_data_api_endpoints_are_available(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(tmp_path / "strategy_factory_market_data"))
    port = _free_port()
    server = _start_server(port)
    try:
        for path in ("/api/strategy-factory/data/status", "/api/strategy-factory/data/inventory"):
            status, headers, body = _fetch(f"http://127.0.0.1:{port}{path}")
            assert status == 200
            assert int(headers["content-length"]) == len(body)
            payload = json.loads(body.decode("utf-8"))
            assert payload["schema_version"].startswith("strategy_factory_data_")
            assert payload.get("prototype_only", True) is True
    finally:
        server.shutdown()
        server.server_close()


def test_operational_snapshot_endpoint_includes_intraday_runtime_fields():
    port = _free_port()
    server = _start_server(port)
    try:
        status, headers, body = _fetch(f"http://127.0.0.1:{port}/api/operational-snapshot")
        assert status == 200
        assert int(headers["content-length"]) == len(body)
        payload = json.loads(body.decode("utf-8"))
        assert payload["intraday_runtime_status"] in {
            "NOT_LOADED",
            "LOADED",
            "STALE",
            "ERROR",
            "PENDING",
            "REFRESH_NEEDED",
            "PROVIDER_FAILED",
        }
        assert "intraday_overlay_available" in payload
        assert "intraday_scheduler_enabled" in payload
        assert "intraday_refresh_status" in payload
        assert "intraday_refresh_message" in payload
        assert "official_promotion_readiness" in payload
        assert payload["official_promotion_readiness"]["execute_enabled"] is False
        assert payload["portfolio_daily"][-1]["date"] == "2026-06-11"
        assert not any(row["date"] == "2026-06-15" for row in payload["portfolio_daily"])
    finally:
        server.shutdown()
        server.server_close()


def test_operational_snapshot_endpoint_refreshes_stale_precomputed_paper_ledger_bytes(tmp_path):
    root = _copy_canonical_root(tmp_path)
    paper_path = root / "dashboard/data/performance/paper_portfolio_daily.json"
    paper_path.parent.mkdir(parents=True)
    paper_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "schema_version": "paper_portfolio_daily_v1",
                    "paper_only": True,
                    "delayed_market_data": True,
                    "not_live_market_data": True,
                    "live_brokerage_execution": False,
                    "is_official_ledger": False,
                    "position_source": "committed_shadow_holdings",
                    "row_count": 1,
                    "latest_date": "2026-06-17",
                },
                "rows": [
                    {
                        "date": "2026-06-17",
                        "trading_date": "2026-06-17",
                        "source": "Paper Performance",
                        "position_source": "committed_shadow_holdings",
                        "paper_only": True,
                        "delayed_market_data": True,
                        "not_live_market_data": True,
                        "live_brokerage_execution": False,
                        "is_official_ledger": False,
                        "nav": 1_005_000,
                        "ending_nav": 1_005_000,
                        "daily_pnl": 569,
                        "daily_return": 0.000566,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.operational_snapshot_bytes = json.dumps(
        {
            "official_promotion_readiness": {"execute_enabled": False},
            "paper_performance_daily": [],
        }
    ).encode("utf-8")
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _fetch(f"http://127.0.0.1:{port}/api/operational-snapshot")
        payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert [row["date"] for row in payload["paper_performance_daily"]] == ["2026-06-17"]
        assert payload["paper_performance_daily_metadata"]["row_count"] == 1
        assert payload["portfolio_daily"][-1]["date"] == "2026-06-11"
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes


def test_operational_snapshot_endpoint_starts_controlled_bootstrap_refresh(monkeypatch, tmp_path):
    root = _copy_canonical_root(tmp_path)
    config_dir = root / "data/config"
    config_dir.mkdir(parents=True)
    (config_dir / "intraday_refresh.yaml").write_text(
        (ROOT / "data/config/intraday_refresh.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    calls = []

    monkeypatch.setattr(
        "scripts.run_workstation_server.refresh_lifecycle_status",
        lambda cfg: {
            "state": "refresh_needed",
            "reason": "missing_current_day_intraday_snapshot",
            "market_status": "Open",
            "market_session_date": "2026-06-22",
            "refresh_needed": True,
            "pending": False,
            "provider_failed": False,
            "refresh_interval_minutes": 30,
        },
    )
    monkeypatch.setattr(
        "scripts.run_workstation_server.run_intraday_refresh",
        lambda **kwargs: calls.append(kwargs) or {"ok": True, "skipped": True, "reason": "test_refresh"},
    )
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    original_bootstrap = WorkstationHandler.request_bootstrap_enabled
    original_in_progress = WorkstationHandler.bootstrap_refresh_in_progress
    original_last = WorkstationHandler.last_bootstrap_refresh_at
    WorkstationHandler.server_root = root
    WorkstationHandler.operational_snapshot_bytes = None
    WorkstationHandler.request_bootstrap_enabled = True
    WorkstationHandler.bootstrap_refresh_in_progress = False
    WorkstationHandler.last_bootstrap_refresh_at = 0.0
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _fetch(f"http://127.0.0.1:{port}/api/operational-snapshot")
        payload = json.loads(body.decode("utf-8"))
        deadline = time.time() + 2
        while not calls and time.time() < deadline:
            time.sleep(0.01)
        assert status == 200
        assert payload["intraday_runtime_status"] == "PENDING"
        assert payload["intraday_refresh_status"] == "pending"
        assert calls
        assert calls[0]["interval_minutes"] == 30
        assert calls[0]["force"] is False
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        WorkstationHandler.request_bootstrap_enabled = original_bootstrap
        WorkstationHandler.bootstrap_refresh_in_progress = original_in_progress
        WorkstationHandler.last_bootstrap_refresh_at = original_last


def test_paper_rebalance_api_persists_pending_and_applied_paper_target(tmp_path):
    root = _copy_canonical_root(tmp_path)
    active = [
        row
        for row in json.loads((root / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"))["strategies"]
        if row.get("membership_state") == "executed"
        and row.get("internal_id") != "WQ_ALPHA_018"
    ]
    weight = 1 / len(active)
    targets = {row["internal_id"]: weight for row in active}
    targets[active[0]["internal_id"]] += 0.01
    targets[active[1]["internal_id"]] -= 0.01
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, _, body = _post_json(
            f"{base}/api/paper-rebalance/plan",
            json.dumps({"target_weights": targets}).encode("utf-8"),
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert payload["ok"] is True
        plan_id = payload["plan"]["plan_id"]
        assert payload["plan"]["execution_mode"] == "Paper Only"
        assert payload["plan"]["live_brokerage_fill"] == "No"
        assert payload["plan"]["official_ledger_mutation"] == "No"

        status, _, body = _post_json(
            f"{base}/api/paper-rebalance/accept",
            json.dumps({"plan_id": plan_id}).encode("utf-8"),
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert payload["plan"]["applied_status"] == "Accepted Pending Application"

        status, _, body = _post_json(
            f"{base}/api/paper-rebalance/apply",
            json.dumps({"plan_id": plan_id}).encode("utf-8"),
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert payload["current_paper_target"]["applied_status"] == "Applied to Paper Allocation"
        assert payload["cost_record"]["official_ledger_mutation"] == "No"

        status, _, body = _fetch(f"{base}/api/paper-rebalance")
        payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert payload["paper_rebalance"]["current_paper_target"]["applied_plan_id"] == plan_id
        assert payload["paper_rebalance"]["latest_cost_record"]["plan_id"] == plan_id
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes


def test_strategy_factory_api_upload_run_and_candidate_flow(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        for path in ("/api/strategy-factory", "/api/strategy-factory/candidates"):
            status, _, body = _fetch(f"{base}{path}")
            payload = json.loads(body.decode("utf-8"))
            assert status == 200
            assert payload["ok"] is True

        boundary = "----strategyfactorytest"
        upload_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="memo.md"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
            "# Research memo\nsector momentum risk filter\n"
            f"\r\n--{boundary}--\r\n"
        ).encode("utf-8")
        status, _, body = _post_bytes(
            f"{base}/api/strategy-factory/upload",
            upload_body,
            {"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept-Encoding": "identity"},
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert payload["saved"][0]["filename"] == "memo.md"
        assert payload["artifact_source_mode"] == "ALPHA_RESEARCH_BRIDGE"
        assert payload["saved"][0]["extraction_status"] == "Extracted"
        assert payload["saved"][0]["analysis"]["document_summary"]
        assert Path(payload["saved"][0]["stored_path"]).exists()
        assert Path(payload["saved"][0]["extracted_text_path"]).exists()
        assert Path(payload["saved"][0]["analysis_path"]).exists()
        assert payload["generated_artifacts"]["research_cards"]
        assert payload["generated_artifacts"]["test_specs"]
        assert payload["generated_artifacts"]["run_plans"]

        status, _, body = _fetch(f"{base}/api/strategy-factory")
        factory = json.loads(body.decode("utf-8"))
        assert factory["stage_counts"]["uploaded_materials"] == 1
        assert factory["stage_counts"]["extracted_materials"] == 1
        assert factory["stage_counts"]["analyzed_records"] == 1
        assert [row["stage"] for row in factory["workflow_stages"]] == [
            "Upload",
            "Extract",
            "Analyze",
            "Candidate Idea",
            "Research Card",
            "Test Spec",
            "Backtest",
            "Robustness",
            "ML Diagnostics",
            "Evidence",
            "Decision",
        ]
        assert factory["stage_statuses"][0]["status"] == "COMPLETED"
        assert {row["stage"] for row in factory["stage_statuses"]} >= {"BACKTEST_RUN", "ML_DIAGNOSTICS_RUN"}

        status, _, body = _post_json(f"{base}/api/strategy-factory/run")
        rejected = json.loads(body.decode("utf-8"))
        assert status == 400
        assert "Select materials for current batch first" in rejected["error"]

        material_id = payload["saved"][0]["material_id"]
        status, _, body = _post_json(
            f"{base}/api/strategy-factory/run",
            json.dumps({"selected_material_ids": [material_id]}).encode("utf-8"),
        )
        run_payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert run_payload["stage"] == "SCOPED_RUN_CREATED"
        assert run_payload["run_manifest"]["selected_material_ids"] == [material_id]
        assert run_payload["run_manifest"]["selected_material_names"] == ["memo.md"]
        generated = run_payload["run_manifest"]["generated_artifacts"]
        assert Path(generated["selected_materials"]).exists()
        assert Path(generated["material_summary"]).exists()
        assert Path(generated["extracted_ideas"]).exists()
        assert Path(generated["run_log"]).exists()
        assert Path(generated["current_run_candidate"]).exists()
        assert Path(generated["current_run_report"]).exists()
        assert Path(run_payload["run"]["batch_manifest_path"]).exists()
        assert Path(run_payload["run"]["run_manifest_path"]).exists()
        candidate = run_payload["candidate"]
        assert candidate["strategy_id"].startswith("RUN_SCOPED_CANDIDATE_")
        assert candidate["strategy_id"] != PROTOTYPE_STRATEGY_ID
        assert candidate["name"].startswith("Current Run:")
        assert candidate["source_evidence"]["run_id"] == run_payload["run"]["run_id"]
        assert candidate["source_evidence"]["source_material_ids"] == [material_id]
        assert candidate["source_evidence"]["selected_material_names"] == ["memo.md"]
        assert [row["material_id"] for row in candidate["source_materials"]] == [material_id]
        assert candidate["current_run"]["current_run_id"] == run_payload["run"]["run_id"]
        assert candidate["current_run"]["selected_material_ids"] == [material_id]

        status, _, body = _fetch(f"{base}/api/strategy-factory/candidates")
        candidates_payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert candidates_payload["candidates"][0]["strategy_id"] == candidate["strategy_id"]
        assert candidates_payload["candidates"][0]["source_evidence"]["source_material_ids"] == [material_id]
        status, _, body = _fetch(f"{base}/api/strategy-factory")
        refreshed = json.loads(body.decode("utf-8"))
        assert refreshed["latest_run"]["run_id"] == run_payload["run"]["run_id"]
        assert refreshed["latest_run_output"]["strategy_id"] == candidate["strategy_id"]
        assert refreshed["current_run_candidates"][0]["source_evidence"]["source_material_ids"] == [material_id]
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_current_run_backtest_writes_blocked_artifacts_without_fake_metrics(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    original_market_csv = os.environ.get("STRATEGY_FACTORY_MARKET_DATA_CSV")
    original_data_root = os.environ.get("STRATEGY_FACTORY_DATA_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    os.environ.pop("STRATEGY_FACTORY_MARKET_DATA_CSV", None)
    os.environ["STRATEGY_FACTORY_DATA_ROOT"] = str(tmp_path / "empty_strategy_factory_market_data")
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, _, body = _post_bytes(
            f"{base}/api/strategy-factory/upload",
            (
                "------sf\r\n"
                'Content-Disposition: form-data; name="files"; filename="copper_memo.md"\r\n'
                "Content-Type: text/markdown\r\n\r\n"
                "Copper price forecasting strategy using 3-month momentum, volatility filter, USD trend, and inventory signal. "
                "Universe: copper ETF/proxy. Benchmark: broad commodities or SPY. Rebalance monthly. No leverage.\r\n"
                "------sf--\r\n"
            ).encode("utf-8"),
            {"Content-Type": "multipart/form-data; boundary=----sf", "Accept-Encoding": "identity"},
        )
        upload = json.loads(body.decode("utf-8"))
        assert status == 201
        material_id = upload["saved"][0]["material_id"]

        status, _, body = _post_json(
            f"{base}/api/strategy-factory/run",
            json.dumps({"selected_material_ids": [material_id]}).encode("utf-8"),
        )
        run_payload = json.loads(body.decode("utf-8"))
        assert status == 201
        run_id = run_payload["run"]["run_id"]

        status, _, body = _post_json(
            f"{base}/api/strategy-factory/backtest-current-run",
            json.dumps({"run_id": run_id}).encode("utf-8"),
        )
        runner_payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert runner_payload["status"] == "BLOCKED"
        assert "BLOCKED_NEEDS_DATA" in runner_payload["reason"]
        artifacts = runner_payload["artifacts"]
        for key in (
            "backtest_run",
            "metrics",
            "daily_returns",
            "equity_curve",
            "equity_curve_svg",
            "drawdown",
            "drawdown_svg",
            "monthly_returns",
            "monthly_returns_table",
            "ml_diagnostics_run",
            "feature_importance_csv",
            "feature_importance_json",
            "prediction_quality",
            "train_test_split",
            "leakage_check",
            "evidence_report",
        ):
            assert Path(artifacts[key]).exists(), key

        backtest = json.loads(Path(artifacts["backtest_run"]).read_text(encoding="utf-8"))
        metrics = json.loads(Path(artifacts["metrics"]).read_text(encoding="utf-8"))
        ml = json.loads(Path(artifacts["ml_diagnostics_run"]).read_text(encoding="utf-8"))
        assert backtest["status"] == "BLOCKED"
        assert backtest["selected_material_ids"] == [material_id]
        assert metrics["status"] == "BLOCKED"
        assert metrics["metrics_available"] is False
        assert "sharpe" not in {key.lower() for key in metrics}
        assert ml["status"] == "BLOCKED"

        status, _, body = _post_json(
            f"{base}/api/strategy-factory/jobs/run-full-current-run",
            json.dumps({"run_id": run_id}).encode("utf-8"),
        )
        full_payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert full_payload["status"] == "BLOCKED"
        assert "DATA_AVAILABILITY_CHECK" in full_payload["reason"]
        assert Path(full_payload["artifacts"]["job_status"]).exists()
        assert Path(full_payload["artifacts"]["run_log"]).exists()
        assert any(stage["stage"] == "BACKTEST_CURRENT_RUN" and stage["status"] == "BLOCKED" for stage in full_payload["stages"])

        status, _, body = _fetch(f"{base}/api/strategy-factory")
        factory = json.loads(body.decode("utf-8"))
        candidate = factory["latest_run_output"]
        assert candidate["strategy_id"] == run_payload["candidate"]["strategy_id"]
        assert candidate["source_evidence"]["source_material_ids"] == [material_id]
        assert candidate["pipeline_stage"] == "BACKTEST_BLOCKED"
        assert candidate["chart_data"]["status"] == "BLOCKED"
        assert candidate["report_path"] == artifacts["evidence_report"]
        assert candidate["full_pipeline_status"] == "BLOCKED"
        assert candidate["full_pipeline_job_status_path"] == full_payload["artifacts"]["job_status"]
        assert not candidate.get("backtest_metrics")
        assert "artifact exists" not in json.dumps(candidate).lower()
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root
        if original_market_csv is None:
            os.environ.pop("STRATEGY_FACTORY_MARKET_DATA_CSV", None)
        else:
            os.environ["STRATEGY_FACTORY_MARKET_DATA_CSV"] = original_market_csv
        if original_data_root is None:
            os.environ.pop("STRATEGY_FACTORY_DATA_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_DATA_ROOT"] = original_data_root


def test_strategy_factory_apply_requires_confirmation(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, _, _ = _post_bytes(
            f"{base}/api/strategy-factory/upload",
            (
                "------sf\r\n"
                'Content-Disposition: form-data; name="files"; filename="memo.md"\r\n'
                "Content-Type: text/markdown\r\n\r\n"
                "sector momentum risk filter\r\n"
                "------sf--\r\n"
            ).encode("utf-8"),
            {"Content-Type": "multipart/form-data; boundary=----sf", "Accept-Encoding": "identity"},
        )
        assert status == 201
        status, _, body = _post_json(f"{base}/api/strategy-factory/run")
        payload = json.loads(body.decode("utf-8"))
        assert status == 400
        assert payload["ok"] is False
        assert "Select materials for current batch first" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_frontend_has_no_hardcoded_strategy_count():
    source = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    start = source.index("function strategyFactoryPage")
    end = source.index("async function refreshStrategyFactory")
    factory_page = source[start:end]
    assert "Strategy Factory" in source
    assert "current_active_strategy_count" in factory_page
    assert "factoryWorkflowStrip" in source
    assert "Material Review / Analysis" in source
    assert "source_derivation_status" in source
    assert "factoryChartGrid" in source
    assert "Styled Strategy Factory Report" in source
    assert "factoryCandidatePortfolioPanel" in source
    assert "data-factory-select" in source
    assert "View Candidate" in source
    assert "View Report" in source
    assert "View Charts" in source
    assert "factoryCandidateWorkspace" in source
    assert "factory-detail-tabs" in source
    assert "Overview" in source
    assert "Portfolio Flow" in source
    assert "data-factory-view" in source
    assert "data-factory-detail-tab" in source
    assert "Charts unavailable: summary metrics exist but candidate-specific time series is missing." in source
    assert "Charts locked: BACKTEST_RUN" not in source
    assert "View all global context" in source
    assert "Total materials available" in source
    assert "Candidate-derived evidence</td><td>None" in source
    assert "Evidence report not generated yet" in source
    assert "Selected Candidate Workspace" in source
    assert "scrollIntoView" not in factory_page
    assert "Remove from Candidate Portfolio" in source
    assert "factoryCandidateDetailPanel" in source
    assert "readable-layout" in source
    assert "factory-section" in source
    assert "factoryStageStatusPanel" in source
    assert "factory-stage-status-panel" in source
    assert "factoryViewportSnapshot" in source
    assert ".main-stage" in source
    assert "docTop" in source
    assert "factorySourceEvidencePanel" in source
    assert "Current Run Candidates / Ideas" in source
    assert "Historical Alpha Candidates" in source
    assert "Prototype Seed Fallback" in source
    assert "factoryCandidateOutputPanel" in source
    assert "factoryCurrentRunCandidates" in source
    assert "factoryRealAlphaCandidates" in source
    assert "Running selected batch..." in source
    assert "Completed selected batch" in source
    assert "data-factory-select" in source
    assert "Candidate-derived evidence" in source
    assert "Selected batch materials" in source
    assert "Global alpha_research context" in source
    assert "Show raw artifact paths" in source
    assert "No selected batch materials. This candidate was not produced by the current selected batch." in source
    assert "timestamp unavailable" in source
    assert "NOT_STARTED" in source
    assert "QUEUED" in source
    assert "COMPLETED" in source
    assert "FAILED" in source
    assert "BLOCKED" in source
    assert "Required artifact" in source
    assert "Last updated" in source
    assert "factoryReportViewer(c)" in source
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")
    assert ".strategy-factory-page.readable-layout" in css
    assert ".factory-candidate-detail.readable" in css
    assert ".factory-report-viewer.readable" in css
    assert "min-width:min(900px,100%)" in css
    assert ".factory-three-column" in css
    assert ".factory-chart-grid.readable" in css
    assert ".factory-candidate-workspace" in css
    assert ".factory-detail-tabs" in css
    assert ".factory-locked-state" in css
    assert ".factory-material-window" in css
    assert "overscroll-behavior:contain" in css
    assert "max-height:340px" in css
    assert ".factory-material-controls" in css
    assert "position:sticky" in css
    assert "data-factory-material-control=\"toggle-window\"" in source
    assert 'factoryMaterialSortKey:"uploaded"' in source
    assert "factoryMaterialSortLabel" in source
    assert "Sorted by:" in source
    assert "Uploaded time" in source
    assert "data-factory-material-sort" in source
    assert "factorySortedMaterials" in source
    assert "factoryMaterialSortHeader(\"Filename\",\"filename\")" in source
    assert "factoryMaterialSortHeader(\"Uploaded\",\"uploaded\")" in source
    assert "flex-wrap:nowrap" in css
    assert "overflow-x:auto" in css
    assert "flex:0 0 118px" in css
    assert "Candidate Detail" in source
    assert "Research Card" in source
    assert "Test Spec" in source
    assert "Backtest Metrics" in source
    assert "Embedded Charts" in source
    assert "ML Diagnostics" in source
    assert "Feature Importance" in source
    assert "Evidence Report Summary" in source
    assert "Candidate portfolio draft artifact path" in source
    assert "Allocation draft status" in source
    assert "Paper apply status" in source
    assert "Requires Allocation Draft + Confirmation" in source
    assert '"17"' not in factory_page
    assert '"18"' not in factory_page
    assert "hardcoded" in factory_page


def test_strategy_factory_pdf_extraction_failure_is_not_false_derivation(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        boundary = "----strategyfactorypdftest"
        upload_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="paper.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
            "%PDF-1.4 fake fixture"
            f"\r\n--{boundary}--\r\n"
        ).encode("utf-8")
        status, _, body = _post_bytes(
            f"{base}/api/strategy-factory/upload",
            upload_body,
            {"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept-Encoding": "identity"},
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert payload["saved"][0]["extraction_status"] == "Unsupported Extraction"

        status, _, body = _fetch(f"{base}/api/strategy-factory")
        factory = json.loads(body.decode("utf-8"))
        assert factory["intake"]["materials"][0]["extraction_status"] == "Unsupported Extraction"
        assert factory["intake"]["materials"][0]["analysis"]["implementation_blockers"]
        assert factory["stage_counts"]["extracted_materials"] == 0
        assert factory["stage_counts"]["extraction_failed"] == 1
        assert factory["stage_counts"]["analyzed_records"] == 0
        extracted_status = next(row for row in factory["stage_statuses"] if row["stage"] == "EXTRACTED")
        assert extracted_status["status"] in {"FAILED", "QUEUED", "BLOCKED"}
        analysis_status = next(row for row in factory["stage_statuses"] if row["stage"] == "MATERIALS_ANALYZED")
        assert analysis_status["status"] == "BLOCKED"
        status, _, body = _post_json(
            f"{base}/api/strategy-factory/run",
            json.dumps({"selected_material_ids": [payload["saved"][0]["material_id"]]}).encode("utf-8"),
        )
        run_payload = json.loads(body.decode("utf-8"))
        assert status == 201
        assert run_payload["candidate"]["source_evidence"]["source_material_ids"] == [payload["saved"][0]["material_id"]]
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_artifact_adapter_reads_existing_alpha_artifacts(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    try:
        batch_id = "BATCH_20260625T000000Z_TEST"
        material_id = "MAT_EXISTING_ALPHA_001_ABCDEF1234"
        text_path = alpha_root / f"strategy_factory_workbench/workbench_data/material_text/{material_id}.txt"
        text_path.write_text("daily price volume momentum with delay-safe execution\n", encoding="utf-8")
        analysis_path = alpha_root / f"strategy_factory_workbench/workbench_data/material_analysis/{material_id}.json"
        analysis_path.write_text(
            json.dumps(
                {
                    "material_id": material_id,
                    "batch_id": batch_id,
                    "filename": "existing.md",
                    "analysis_status": "ANALYZED",
                    "extraction_status": "EXTRACTED_TEXT",
                    "detected_keywords": ["momentum", "daily price-volume"],
                    "candidate_ideas": [{"name": "Daily Momentum Research Idea", "description": "Delay-safe daily momentum."}],
                    "classification_guess": "NOW_TESTABLE",
                    "testability": "POTENTIALLY_TESTABLE_WITH_DELAY_SAFE_DAILY_OHLCV",
                }
            ),
            encoding="utf-8",
        )
        (alpha_root / f"strategy_factory_workbench/workbench_data/upload_batches/{batch_id}.json").write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "created_at": "2026-06-25T00:00:00Z",
                    "files": [
                        {
                            "material_id": material_id,
                            "batch_id": batch_id,
                            "original_filename": "existing.md",
                            "stored_relative_path": "strategy_factory_workbench/workbench_data/uploads/existing.md",
                            "file_ext": ".md",
                            "extraction_status": "EXTRACTED_TEXT",
                            "extraction_phase_status": "EXTRACTED",
                            "extracted_text_path": f"strategy_factory_workbench/workbench_data/material_text/{material_id}.txt",
                            "analysis_status": "ANALYZED",
                            "analysis_path": f"strategy_factory_workbench/workbench_data/material_analysis/{material_id}.json",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (alpha_root / "strategy_factory_workbench/workbench_data/candidate_idea_registry.json").write_text(
            json.dumps([{"idea_id": "IDEA_EXISTING", "title": "Daily Momentum Research Idea"}]),
            encoding="utf-8",
        )
        (alpha_root / "strategy_factory/research_cards/EXISTING_research_card.md").write_text("# Existing Card\n", encoding="utf-8")
        (alpha_root / "strategy_factory/codex_test_specs/EXISTING_test_spec.md").write_text("# Existing Spec\n", encoding="utf-8")
        (alpha_root / "strategy_factory/experiments/EXISTING_EXP/outputs").mkdir(parents=True)
        (alpha_root / "strategy_factory/experiments/EXISTING_EXP/outputs/baseline_summary.json").write_text("{}", encoding="utf-8")
        snapshot = load_alpha_snapshot(root)
        assert snapshot is not None
        assert snapshot["counts"]["uploaded_materials"] == 1
        assert snapshot["counts"]["extracted_materials"] == 1
        assert snapshot["counts"]["analyzed_records"] == 1
        assert snapshot["counts"]["candidate_ideas"] == 1
        assert snapshot["counts"]["research_cards"] == 1
        assert snapshot["counts"]["test_specs"] == 1
        assert snapshot["counts"]["backtest_results"] == 1
    finally:
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_real_candidate_lineage_and_metrics_precede_prototype(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    try:
        strategy_id = "REAL_ALPHA_CANDIDATE_V0"
        exp = alpha_root / f"strategy_factory/experiments/{strategy_id}_EXPERIMENT_V0/outputs"
        exp.mkdir(parents=True)
        (exp / "baseline_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "BASELINE_SUMMARY_V0",
                    "strategy_id": strategy_id,
                    "strategy_name": "Real Alpha Candidate V0",
                    "benchmark": "SPY",
                    "decision_status": "WATCH_ONLY",
                    "universe": "US sector ETF proxy universe",
                    "cost_assumptions": {"transaction_cost_bps": 5.0},
                    "test_period": {"start_date": "2020-01-01", "end_date": "2024-12-31"},
                    "key_metrics": {
                        "sharpe": 1.23,
                        "annualized_return": 0.14,
                        "max_drawdown": -0.11,
                        "annualized_volatility": 0.18,
                        "average_turnover": 0.27,
                        "benchmark_correlation": 0.42,
                    },
                }
            ),
            encoding="utf-8",
        )
        csv_rows = ["date,strategy,gross_return,transaction_cost,cost_drag,net_return,turnover,benchmark_return,base_cost_bps_per_side"]
        for idx in range(70):
            day = idx + 1
            ret = 0.001 if idx % 3 else -0.0005
            bench = 0.0008 if idx % 4 else -0.0002
            csv_rows.append(f"2020-01-{day:02d},{strategy_id},{ret},0.00005,0.00005,{ret - 0.00005},0.10,{bench},5.0")
        (exp / "daily_strategy_returns.csv").write_text("\n".join(csv_rows), encoding="utf-8")
        (exp / "ml_diagnostics_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "ML_DIAGNOSTICS_SUMMARY_V0",
                    "strategy_id": strategy_id,
                    "ml_diagnostics_decision": "ML_WATCH_ONLY",
                    "top_diagnostic_model": "ridge",
                    "top_diagnostic_metric": "test_score",
                    "top_diagnostic_value": 0.03,
                }
            ),
            encoding="utf-8",
        )
        (alpha_root / f"strategy_factory/research_cards/{strategy_id}_research_card.md").write_text("# Research Card\n", encoding="utf-8")
        (alpha_root / f"strategy_factory/codex_test_specs/{strategy_id}_test_spec.md").write_text("# Test Spec\n", encoding="utf-8")
        (alpha_root / f"strategy_factory/evidence_reports/{strategy_id}").mkdir(parents=True)
        (alpha_root / f"strategy_factory/evidence_reports/{strategy_id}/evidence_report.md").write_text("# Evidence\nSummary\n", encoding="utf-8")
        snapshot = load_alpha_snapshot(root)
        assert snapshot is not None
        assert snapshot["candidates"][0]["strategy_id"] == strategy_id
        workstation_candidates = list_candidates(root)
        assert workstation_candidates[0]["strategy_id"] == strategy_id
        assert any(row["strategy_id"] == PROTOTYPE_STRATEGY_ID for row in workstation_candidates)
        assert [row["strategy_id"] for row in workstation_candidates].index(strategy_id) < [
            row["strategy_id"] for row in workstation_candidates
        ].index(PROTOTYPE_STRATEGY_ID)
        candidate = snapshot["candidates"][0]
        assert candidate["backtest_metrics"]["sharpe"] == 1.23
        assert candidate["backtest_metrics"]["annual_return"] == 0.14
        assert candidate["backtest_metrics"]["max_drawdown"] == -0.11
        assert candidate["backtest_metrics"]["volatility"] == 0.18
        assert candidate["backtest_metrics"]["turnover"] == 0.27
        assert candidate["benchmark"] == "SPY"
        assert candidate["date_range"] == "2020-01-01 to 2024-12-31"
        assert candidate["cost_assumption"] == "5.0 bps"
        assert candidate["chart_data"]["status"] == "AVAILABLE"
        assert candidate["chart_data"]["source_artifact_path"].endswith("daily_strategy_returns.csv")
        assert candidate["chart_data"]["equity_curve"]["series"][0]["values"]
        assert candidate["chart_data"]["equity_curve"]["series"][1]["values"]
        assert candidate["chart_data"]["drawdown"]["series"][0]["values"]
        assert candidate["chart_data"]["rolling_sharpe"]["series"][0]["values"]
        assert candidate["chart_data"]["monthly_returns"]["rows"]
        assert candidate["chart_data"]["return_distribution"]["bins"]
        assert candidate["chart_data"]["turnover_cost"]["rows"]
        assert not candidate["chart_previews"]
        assert "artifact exists" not in json.dumps(candidate)
        assert candidate["source_evidence"]["artifact_chain"]["backtest"].endswith("baseline_summary.json")
        assert candidate["source_evidence"]["artifact_chain"]["ml_diagnostics"].endswith("ml_diagnostics_summary.json")
        assert candidate["source_evidence"]["artifact_chain"]["evidence"].endswith("evidence_report.md")
    finally:
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_summary_only_backtest_does_not_fake_charts(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    try:
        strategy_id = "SUMMARY_ONLY_CANDIDATE_V0"
        exp = alpha_root / f"strategy_factory/experiments/{strategy_id}_EXPERIMENT_V0/outputs"
        exp.mkdir(parents=True)
        (exp / "baseline_summary.json").write_text(
            json.dumps(
                {
                    "strategy_id": strategy_id,
                    "benchmark": "SPY",
                    "cost_assumptions": {"transaction_cost_bps": 5.0},
                    "key_metrics": {
                        "sharpe": 0.4,
                        "annualized_return": 0.03,
                        "max_drawdown": -0.08,
                    },
                }
            ),
            encoding="utf-8",
        )
        snapshot = load_alpha_snapshot(root)
        candidate = next(row for row in snapshot["candidates"] if row["strategy_id"] == strategy_id)
        assert candidate["chart_data"]["status"] == "SUMMARY_ONLY"
        assert candidate["chart_data"]["message"] == "Chart unavailable: missing real backtest series."
        assert candidate["chart_data"]["summary_metrics"]["sharpe"] == 0.4
        assert candidate["chart_previews"] == []
    finally:
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_uploads_do_not_overwrite_existing_alpha_candidates(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    preserved_card = alpha_root / "strategy_factory/research_cards/PRESERVED_research_card.md"
    preserved_card.write_text("# Preserved\n", encoding="utf-8")
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        body = (
            "------sf2\r\n"
            'Content-Disposition: form-data; name="files"; filename="new_note.md"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
            "daily ohlcv momentum delay safe\r\n"
            "------sf2--\r\n"
        ).encode("utf-8")
        status, _, payload_bytes = _post_bytes(
            f"{base}/api/strategy-factory/upload",
            body,
            {"Content-Type": "multipart/form-data; boundary=----sf2", "Accept-Encoding": "identity"},
        )
        payload = json.loads(payload_bytes.decode("utf-8"))
        assert status == 201
        assert preserved_card.read_text(encoding="utf-8") == "# Preserved\n"
        assert Path(payload["saved"][0]["analysis_path"]).exists()
        cards = list((alpha_root / "strategy_factory/research_cards").glob("*.md"))
        assert preserved_card in cards
        assert len(cards) >= 2
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_strategy_factory_report_viewer_blocks_when_evidence_missing(tmp_path):
    root = _copy_canonical_root(tmp_path)
    alpha_root = _create_alpha_research_root(tmp_path)
    original_alpha_root = os.environ.get("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT")
    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = str(alpha_root)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = root
    WorkstationHandler.warm_operational_snapshot_cache(root)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, _, _ = _post_bytes(
            f"{base}/api/strategy-factory/upload",
            (
                "------sf3\r\n"
                'Content-Disposition: form-data; name="files"; filename="memo.md"\r\n'
                "Content-Type: text/markdown\r\n\r\n"
                "daily momentum delay safe\r\n"
                "------sf3--\r\n"
            ).encode("utf-8"),
            {"Content-Type": "multipart/form-data; boundary=----sf3", "Accept-Encoding": "identity"},
        )
        assert status == 201
        status, _, body = _fetch(f"{base}/api/strategy-factory")
        factory = json.loads(body.decode("utf-8"))
        material_id = factory["intake"]["materials"][0]["material_id"]
        status, _, body = _post_json(
            f"{base}/api/strategy-factory/run",
            json.dumps({"selected_material_ids": [material_id]}).encode("utf-8"),
        )
        candidate = json.loads(body.decode("utf-8"))["candidate"]
        status, _, body = _fetch(f"{base}/api/strategy-factory/report/{candidate['strategy_id']}")
        report = body.decode("utf-8")
        assert status == 200
        assert "Current Run Report" in report
        assert "backtest" in report.lower()
        assert "NOT_IMPLEMENTED / BLOCKED" in report
        assert "ml" in report.lower()
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes
        if original_alpha_root is None:
            os.environ.pop("STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT", None)
        else:
            os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = original_alpha_root


def test_generated_artifact_contract_documents_runtime_and_research_layers():
    contract = artifact_contract()
    runtime_names = {row["name"] for row in contract["runtime_artifacts"]}
    research_names = {row["name"] for row in contract["generated_research_artifacts"]}
    assert "dashboard_artifact" in runtime_names
    assert "strategy_factory_research" in research_names
    assert contract["rules"]["market_data"] == "Do not fabricate market, performance, brokerage, or live fill data."


def test_contract_bootstrap_artifact_is_safe_non_live(tmp_path):
    root = tmp_path
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "canonical_operational.json").write_text(
        json.dumps(
            {
                "portfolio_summary": {"as_of_date": "2026-06-12", "nav": 1_000_000},
                "strategies": [{"internal_id": "S1", "display_name": "Paper Sleeve 1", "current_weight": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    artifact, state = ensure_dashboard_artifact(root)
    assert state["state"] == "initialized"
    assert validate_runtime_bootstrap_artifact(artifact) == []
    assert artifact["data_classification"]["is_live_portfolio_data"] is False
    assert artifact["data_classification"]["live_brokerage_fills_represented"] is False


def test_refresh_data_does_not_require_missing_dashboard_artifact(tmp_path, monkeypatch):
    root = tmp_path
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
    config_dir = root / "data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "intraday_refresh.yaml").write_text(
        """
intraday_refresh:
  enabled: true
  default_interval_minutes: 5
  allowed_intervals_minutes: [5, 10, 30]
  provider: yfinance
  bar_interval_by_refresh:
    5: 5m
    10: 5m
    30: 15m
  timezone: America/New_York
  regular_session_only: true
  stale_after_minutes:
    5: 10
    10: 20
    30: 45
  request_timeout_seconds: 20
  retry_attempts: 1
  backoff_seconds: [1]
  min_success_ticker_ratio: 0.6
  incomplete_bar_label: incomplete_current_bar
  snapshot_dir: output/intraday_snapshots
  latest_pointer_path: output/intraday_latest.json
  status_path: output/intraday_refresh_status.json
  lock_path: output/intraday_refresh.lock
  shadow_database_path: output/shadow/strategy_shadow.db
  market_holidays: []
""".lstrip(),
        encoding="utf-8",
    )
    (canonical_dir / "canonical_operational.json").write_text(
        json.dumps(
            {
                "portfolio_summary": {"as_of_date": "2026-06-12", "nav": 1_000_000},
                "strategies": [
                    {
                        "internal_id": "S1",
                        "display_name": "Paper Sleeve 1",
                        "membership_state": "executed",
                        "current_weight": 1.0,
                    }
                ],
                "holdings": [
                    {"date": "2026-06-12", "strategy_id": "S1", "ticker": "SPY", "target_weight": 1.0}
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = {}

    def _refresh_stub(**kwargs):
        artifact_path = Path(kwargs["artifact_path"])
        calls["artifact_exists"] = artifact_path.exists()
        return {
            "ok": True,
            "refresh_status": "success",
            "position_source": "committed_shadow_holdings",
            "legacy_artifact_position_estimate_authoritative": False,
            "paper_performance_update": {
                "portfolio_row_updated": True,
                "strategy_rows_updated": 0,
                "trading_date": "2026-06-17",
                "refresh_status": "fresh",
            },
        }

    monkeypatch.setattr("scripts.run_workstation_server.run_intraday_refresh", _refresh_stub)
    original_root = WorkstationHandler.server_root
    original_artifact = WorkstationHandler.deployment_artifact
    WorkstationHandler.server_root = root
    WorkstationHandler.deployment_artifact = None
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _post_json(f"http://127.0.0.1:{port}/api/refresh-data")
        payload = json.loads(body.decode("utf-8"))
        artifact_path = root / "output" / "dashboard_artifact.json"
        assert status == 200
        assert calls["artifact_exists"] is False
        assert artifact_path.exists() is False
        assert payload["ok"] is True
        assert payload["refresh_status"] == "success"
        assert payload["refresh_artifact"]["state"] == "not_required"
        assert payload["refresh_artifact"]["reason"] == "refresh_scheme_b_committed_shadow_holdings"
        assert payload["refresh_artifact"]["legacy_artifact_position_estimate_authoritative"] is False
        assert payload["paper_performance_update"]["portfolio_row_updated"] is True
        assert payload["paper_performance_update"]["strategy_rows_updated"] == 0
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.deployment_artifact = original_artifact


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
