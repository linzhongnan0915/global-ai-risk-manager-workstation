from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts.run_workstation_server import WorkstationHandler
from src.automation.risk_evidence import (
    build_risk_evidence_artifact,
    read_latest_risk_evidence_artifact,
    write_risk_evidence_artifact,
)


def _rows(values: list[float]) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    nav = 100.0
    rows = []
    for offset, value in enumerate(values):
        nav *= 1.0 + value
        rows.append(
            {
                "date": (start + timedelta(days=offset)).date().isoformat(),
                "daily_return": value,
                "ending_nav": nav,
            }
        )
    return rows


def _strategy_rows(values: list[float], strategy_uid: str = "STRATEGY_TEST") -> list[dict]:
    rows = []
    for row in _rows(values):
        rows.append(
            {
                "date": row["date"],
                "strategy_id": strategy_uid,
                "net_return": row["daily_return"],
                "ending_sleeve_nav": row["ending_nav"],
            }
        )
    return rows


def _payload(values: list[float]) -> dict:
    return {
        "portfolio_daily": _rows(values),
        "strategy_daily": _strategy_rows(values),
    }


def _write_input(root: Path, payload: dict) -> Path:
    path = root / "dashboard/data/canonical_operational.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_port() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), WorkstationHandler)
    port = int(server.server_address[1])
    server.server_close()
    return port


def _fetch_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_json(url: str) -> tuple[int, dict]:
    request = Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_synthetic_returns_compute_tail_loss_and_drawdown() -> None:
    returns = [-0.10, -0.08, -0.05, -0.03, -0.02] + [0.01] * 35
    artifact = build_risk_evidence_artifact(
        Path("."),
        now=datetime(2026, 6, 30, tzinfo=timezone.utc),
        input_payload=_payload(returns),
        input_artifacts=["synthetic"],
    )

    metrics = artifact["portfolio_risk_evidence"]["risk_metrics"]
    assert metrics["historical_var_95"]["status"] == "COMPUTED"
    assert metrics["historical_var_95"]["value"] == pytest.approx(0.08)
    assert metrics["historical_cvar_95"]["value"] == pytest.approx(0.09)
    assert metrics["max_drawdown"]["value"] < 0
    assert metrics["worst_1_day_return"]["value"] == pytest.approx(-0.10)
    assert metrics["realized_volatility"]["annualized"] is False


def test_insufficient_history_is_labeled_without_available_tail_claim() -> None:
    artifact = build_risk_evidence_artifact(
        Path("."),
        input_payload=_payload([-0.02, 0.01, -0.01]),
        input_artifacts=["synthetic"],
    )

    evidence = artifact["portfolio_risk_evidence"]
    assert evidence["status"] == "PARTIAL"
    assert evidence["risk_metrics"]["historical_var_95"]["status"] == "INSUFFICIENT_HISTORY"
    assert evidence["risk_metrics"]["historical_cvar_95"]["status"] == "INSUFFICIENT_HISTORY"
    assert "Insufficient Risk History" in evidence["labels"]
    assert "Missing Risk Evidence" in evidence["labels"]


def test_artifact_writer_sets_review_only_safety_flags(tmp_path: Path) -> None:
    result = write_risk_evidence_artifact(
        tmp_path,
        now=datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
        input_payload=_payload([0.01] * 20),
        input_artifacts=["synthetic"],
    )

    assert result["ok"] is True
    assert result["financial_state_mutated"] is False
    assert result["paper_apply_created"] is False
    assert result["approved_plan_created"] is False
    assert (tmp_path / result["artifact_path"]).exists()


def test_read_latest_missing_state_returns_missing_artifact(tmp_path: Path) -> None:
    result = read_latest_risk_evidence_artifact(tmp_path)

    assert result["ok"] is False
    assert result["status"] == "MISSING_ARTIFACT"
    assert result["financial_state_mutated"] is False


def test_generate_endpoint_writes_only_risk_artifact_without_canonical_mutation(tmp_path: Path) -> None:
    input_path = _write_input(tmp_path, _payload([-0.01, 0.02, -0.03, 0.01, -0.02]))
    before_hash = _hash(input_path)
    original_root = WorkstationHandler.server_root
    original_bytes = WorkstationHandler.operational_snapshot_bytes
    WorkstationHandler.server_root = tmp_path
    WorkstationHandler.operational_snapshot_bytes = None
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        missing_status, missing = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/risk-evidence/latest")
        status, generated = _post_json(f"http://127.0.0.1:{port}/api/automation-intelligence/risk-evidence/generate")
        latest_status, latest = _fetch_json(f"http://127.0.0.1:{port}/api/automation-intelligence/risk-evidence/latest")
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.operational_snapshot_bytes = original_bytes

    assert missing_status == 404
    assert missing["status"] == "MISSING_ARTIFACT"
    assert status == 201
    assert generated["financial_state_mutated"] is False
    assert generated["paper_apply_created"] is False
    assert generated["approved_plan_created"] is False
    assert latest_status == 200
    assert latest["artifact"]["source"] == "risk_evidence_artifact_v0"
    assert _hash(input_path) == before_hash


def test_generated_artifact_exposes_no_apply_or_approval_flags(tmp_path: Path) -> None:
    result = write_risk_evidence_artifact(
        tmp_path,
        input_payload=_payload([0.01, -0.01, 0.02, -0.02, 0.005]),
        input_artifacts=["synthetic"],
    )

    artifact = result["artifact"]
    assert artifact["paper_shadow_only"] is True
    assert artifact["financial_state_mutated"] is False
    assert artifact["paper_apply_created"] is False
    assert artifact["approved_plan_created"] is False
