from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scripts.run_workstation_server import WorkstationHandler
from src.strategies.strategy_factory_admission import (
    BLOCKED_REASON,
    activate_portfolio_candidate,
    add_candidate,
    add_portfolio_candidate,
    add_to_paper_sandbox,
    apply_to_paper,
    candidate_id_for,
    generate_allocation_draft,
    get_admission_status,
    get_portfolio_candidates_status,
    get_sandbox_status,
    run_risk_review,
    sandbox_id_for,
)


RUN_ID = "SF_RUN_ADMISSION_TEST"
BLOCKED_VARIANT = "COPPER_PROXY_BLOCKED_V1"
ELIGIBLE_VARIANT = "SYNTHETIC_ELIGIBLE_ADMISSION_TEST_V1"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_variant_fixture(
    root: Path,
    variant_id: str,
    *,
    candidate_allowed: bool,
    synthetic: bool = False,
    proxy_only: bool = True,
    evidence_score: float = 55.0,
    recommendation: str | None = None,
    metrics_status: str = "COMPLETED",
) -> None:
    variants_dir = root / "output" / "strategy_factory" / "runs" / RUN_ID / "variants"
    variant_dir = variants_dir / variant_id
    evaluation_dir = variant_dir / "evaluation"
    spec = {
        "variant_id": variant_id,
        "variant_name": variant_id.replace("_", " ").title(),
        "source_run_id": RUN_ID,
        "source_material_ids": ["material_fixture"],
        "thesis": "Synthetic admission fixture thesis." if synthetic else "Copper proxy fixture thesis.",
        "signal_formula": "Long proxy when trend and risk checks pass.",
        "universe_or_proxy": ["SPY"] if synthetic else ["CPER"],
        "benchmark": "SPY" if synthetic else "DBC",
        "features": ["momentum_21d", "momentum_63d"],
        "model_plan": {"primary": "ridge"},
        "data_requirements": ["SPY"] if synthetic else ["CPER", "DBC"],
        "testability_status": "READY_TO_TEST" if synthetic else "PROXY_ONLY",
        "synthetic_admission_test_only": synthetic,
    }
    _write_json(variant_dir / "variant_spec.json", spec)
    _write_json(
        evaluation_dir / "variant_metrics.json",
        {
            "status": metrics_status,
            "sharpe": 1.1 if synthetic else 0.31,
            "annual_return": 0.12 if synthetic else 0.031,
            "max_drawdown": -0.08 if synthetic else -0.18,
            "volatility": 0.11,
            "turnover": 0.02,
            "benchmark_annual_return": 0.08,
            "prototype_proxy_only": proxy_only,
        },
    )
    _write_json(
        evaluation_dir / "variant_ml_diagnostics_run.json",
        {
            "status": "COMPLETED",
            "model": "ridge",
            "prediction_quality": {"spearman_ic": 0.08 if synthetic else 0.01},
            "direction_quality": {"direction_hit_rate": 0.56 if synthetic else 0.51},
        },
    )
    _write_json(
        evaluation_dir / "variant_robustness_run.json",
        {
            "status": "COMPLETED",
            "summary": {
                "overall_status": "PASS" if synthetic else "WATCH",
                "cost_sensitivity_status": "PASS",
                "lookback_sensitivity_status": "PASS",
                "benchmark_status": "PASS" if synthetic else "WATCH",
            },
        },
    )
    _write_json(
        evaluation_dir / "variant_decision.json",
        {
            "variant_id": variant_id,
            "recommendation": recommendation or ("Watch" if not candidate_allowed else "Candidate"),
            "candidate_allowed": candidate_allowed,
            "candidate": candidate_allowed,
            "reason": "Synthetic test evidence passes admission checks." if candidate_allowed else BLOCKED_REASON,
        },
    )
    (evaluation_dir / "variant_evidence_report.md").write_text("# Evidence\n\nSynthetic fixture only.\n", encoding="utf-8")
    existing_registry = _read_json(variants_dir / "variant_registry.json", {"variants": []})
    existing_ranking = _read_json(variants_dir / "variant_ranking.json", {"rankings": []})
    existing_registry["source_run_id"] = RUN_ID
    existing_registry["variants"] = [row for row in existing_registry["variants"] if row.get("variant_id") != variant_id] + [
        {
            "variant_id": variant_id,
            "variant_name": spec["variant_name"],
            "universe_or_proxy": spec["universe_or_proxy"],
            "benchmark": spec["benchmark"],
            "synthetic_admission_test_only": synthetic,
        }
    ]
    existing_ranking["source_run_id"] = RUN_ID
    existing_ranking["rankings"] = [row for row in existing_ranking["rankings"] if row.get("variant_id") != variant_id] + [
        {
            "rank": 1 if synthetic else 2,
            "variant_id": variant_id,
            "variant_name": spec["variant_name"],
            "evidence_score": evidence_score,
            "performance_score": 75 if synthetic else 40,
            "robustness_score": 75 if synthetic else 40,
            "ml_score": 70 if synthetic else 35,
            "data_quality_score": 80 if synthetic else 40,
            "risk_penalty": 5 if synthetic else 35,
            "final_recommendation": recommendation or ("Candidate" if candidate_allowed else "Watch"),
            "candidate_allowed": candidate_allowed,
            "reason": "Synthetic admission fixture only." if synthetic else BLOCKED_REASON,
        }
    ]
    existing_ranking["best_variant"] = existing_ranking["rankings"][0]
    _write_json(variants_dir / "variant_registry.json", existing_registry)
    _write_json(variants_dir / "variant_ranking.json", existing_ranking)


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_true_live_trading(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"live_trading", "brokerage_execution"}:
                assert item is False
            _assert_no_true_live_trading(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_true_live_trading(item)


def _write_canonical_display_ids(root: Path, ordinary_count: int, *, include_combined: bool = False) -> None:
    strategies = [
        {
            "display_id": f"#{idx:06d}",
            "internal_id": f"STRATEGY_{idx:06d}",
            "membership_state": "executed",
            "family": "Ordinary",
        }
        for idx in range(1, ordinary_count + 1)
    ]
    if include_combined:
        strategies.append(
            {
                "display_id": "#COMBINED",
                "internal_id": "COMBINED_PORTFOLIO",
                "membership_state": "executed",
                "family": "Combined",
                "strategy_type": "COMPOSITE",
            }
        )
    _write_json(root / "dashboard" / "data" / "canonical_operational.json", {"strategies": strategies})


def test_copper_blocked_variant_cannot_be_added(tmp_path: Path) -> None:
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True)

    result = add_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT)
    candidate_id = candidate_id_for(RUN_ID, BLOCKED_VARIANT)

    assert result["ok"] is False
    assert result["state"] == "CANDIDATE_BLOCKED"
    assert result["message"] == BLOCKED_REASON
    assert not (tmp_path / "output" / "strategy_factory" / "admission" / candidate_id / "candidate_admission.json").exists()
    assert (tmp_path / "output" / "strategy_factory" / "admission" / candidate_id / "admission_log.json").exists()


def test_watch_variant_can_enter_paper_sandbox_only_with_confirmation(tmp_path: Path) -> None:
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, evidence_score=58)
    sandbox_id = sandbox_id_for(RUN_ID, BLOCKED_VARIANT)
    sandbox_dir = tmp_path / "output" / "strategy_factory" / "sandbox" / sandbox_id

    strict = add_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT)
    assert strict["state"] == "CANDIDATE_BLOCKED"
    assert not (tmp_path / "output" / "strategy_factory" / "admission" / candidate_id_for(RUN_ID, BLOCKED_VARIANT) / "candidate_admission.json").exists()

    try:
        add_to_paper_sandbox(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=False)
    except ValueError as exc:
        assert "explicit user_confirmation=true required" in str(exc)
    else:
        raise AssertionError("paper sandbox should require explicit user confirmation")
    assert not (sandbox_dir / "sandbox_admission.json").exists()

    result = add_to_paper_sandbox(
        tmp_path,
        RUN_ID,
        BLOCKED_VARIANT,
        user_confirmation=True,
        target_weight=0.02,
        override_reason="Fixture confirms research-only paper sandbox monitoring.",
    )
    assert result["ok"] is True
    assert result["state"] == "SANDBOX_MONITORING"
    assert result["sandbox_id"] == sandbox_id

    expected_artifacts = [
        "sandbox_admission.json",
        "sandbox_paper_sleeve.json",
        "sandbox_allocation_draft.json",
        "sandbox_transaction_cost_estimate.json",
        "sandbox_risk_impact_estimate.json",
        "sandbox_combined_recompute_request.json",
        "sandbox_monitoring_status.json",
    ]
    for name in expected_artifacts:
        path = sandbox_dir / name
        assert path.exists()
        payload = _read_json(path, {})
        assert payload["sandbox_id"] == sandbox_id
        assert payload["run_id"] == RUN_ID
        assert payload["source_run_id"] == RUN_ID
        assert payload["variant_id"] == BLOCKED_VARIANT
        assert payload["strategy_name"]
        assert payload["decision_status"] == "SANDBOX_MONITORING"
        assert payload["sandbox_only_reason"]
        assert payload["strict_admission_status"] == "BLOCKED"
        assert payload["candidate_allowed"] is False
        assert payload["recommendation"] == "Watch"
        assert payload["evidence_score"] == 58
        assert payload["target_weight"] <= 0.01
        assert payload["simulated"] is True
        assert payload["paper_only"] is True
        assert payload["live_trading"] is False
        assert payload["brokerage_execution"] is False
        assert payload["user_confirmed"] is True
        assert payload["in_portfolio_monitor"] is True
        assert payload["ready_for_refresh"] is True
        assert payload["portfolio_monitor_status"] == "PENDING_FIRST_REFRESH"
        assert payload["next_refresh_required"] is True
        assert payload["status"] == "SANDBOX_MONITORING"
        assert payload["created_at"]
        assert payload["key_metrics"]["sharpe"] == 0.31
        assert payload["key_metrics"]["max_drawdown"] == -0.18
        assert payload["key_metrics"]["annualized_return"] == 0.031
        assert payload["key_metrics"]["volatility"] == 0.11
        assert payload["key_metrics"]["turnover"] == 0.02
        assert payload["key_metrics"]["evidence_score"] == 58
        assert payload["key_metrics"]["data_quality_status"] == "PROXY_ONLY"
        assert payload["key_metrics"]["ml_support"]["model_type"] == "ridge"
        assert payload["next_required_validation_steps"]
        _assert_no_true_live_trading(payload)

    sleeve = _read_json(sandbox_dir / "sandbox_paper_sleeve.json", {})
    assert sleeve["sandbox_sleeve_id"].startswith("PAPER_SANDBOX_SLEEVE_")
    assert sleeve["approved_strategy"] is False
    assert sleeve["not_institutional_validation"] is True
    assert sleeve["combined_recompute_required"] is True

    transaction = _read_json(sandbox_dir / "sandbox_transaction_cost_estimate.json", {})
    assert transaction["estimated_cost_usd"] > 0
    monitoring = _read_json(sandbox_dir / "sandbox_monitoring_status.json", {})
    assert monitoring["downstream_targets"]["Strategy Monitor"] == "PENDING_NEXT_PAPER_REFRESH"
    assert monitoring["downstream_targets"]["Portfolio NAV/P&L"] == "PENDING_NEXT_PAPER_REFRESH"
    assert monitoring["downstream_targets"]["Risk Contribution"] == "PENDING_RISK_RECALCULATION"
    assert monitoring["downstream_targets"]["Combined Strategy"] == "PENDING_COMBINED_RECOMPUTE"
    assert monitoring["nav_pnl_fabricated"] is False

    status = get_sandbox_status(tmp_path, RUN_ID, BLOCKED_VARIANT)
    assert status["state"] == "SANDBOX_MONITORING"
    assert status["live_trading"] is False
    assert not (tmp_path / "dashboard" / "data" / "canonical_operational.json").exists()
    assert not (tmp_path / "dashboard" / "data" / "performance" / "paper_portfolio_daily.json").exists()
    assert not (tmp_path / "dashboard" / "data" / "performance" / "paper_strategy_daily.json").exists()
    assert not (tmp_path / "output" / "paper_ledger.json").exists()
    assert not (tmp_path / "output" / "combined").exists()


def test_modify_variant_can_enter_portfolio_monitor_with_candidate_allowed_false(tmp_path: Path) -> None:
    variant_id = "COPPER_MODIFY_MONITOR_FIXTURE"
    _write_variant_fixture(
        tmp_path,
        variant_id,
        candidate_allowed=False,
        proxy_only=True,
        evidence_score=52,
        recommendation="Modify",
    )

    strict = add_candidate(tmp_path, RUN_ID, variant_id)
    assert strict["state"] == "CANDIDATE_BLOCKED"

    result = add_to_paper_sandbox(
        tmp_path,
        RUN_ID,
        variant_id,
        user_confirmation=True,
        override_reason="User confirmed Add to Portfolio for simulated research monitoring.",
    )

    assert result["ok"] is True
    admission = result["sandbox_admission"]
    assert admission["candidate_allowed"] is False
    assert admission["recommendation"] == "Modify"
    assert admission["in_portfolio_monitor"] is True
    assert admission["ready_for_refresh"] is True
    assert admission["portfolio_monitor_status"] == "PENDING_FIRST_REFRESH"
    assert admission["live_trading"] is False
    assert admission["brokerage_execution"] is False


def test_paper_sandbox_missing_metrics_are_recorded_as_missing_evidence_inputs(tmp_path: Path) -> None:
    variant_id = "WATCH_MISSING_METRIC_SANDBOX_TEST_V1"
    _write_variant_fixture(tmp_path, variant_id, candidate_allowed=False, proxy_only=True, evidence_score=50)
    metrics_path = tmp_path / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id / "evaluation" / "variant_metrics.json"
    metrics = _read_json(metrics_path, {})
    metrics.pop("volatility", None)
    metrics.pop("turnover", None)
    metrics.pop("cost_assumption", None)
    _write_json(metrics_path, metrics)

    result = add_to_paper_sandbox(tmp_path, RUN_ID, variant_id, user_confirmation=True)
    assert result["ok"] is True
    admission = _read_json(
        tmp_path / "output" / "strategy_factory" / "sandbox" / sandbox_id_for(RUN_ID, variant_id) / "sandbox_admission.json",
        {},
    )
    assert admission["key_metrics"]["volatility"] is None
    assert admission["key_metrics"]["turnover"] is None
    assert admission["key_metrics"]["transaction_cost_assumption"] is None


def test_reject_or_blocked_variant_cannot_enter_paper_sandbox(tmp_path: Path) -> None:
    reject_variant = "REJECTED_SANDBOX_TEST_V1"
    data_blocked_variant = "DATA_BLOCKED_SANDBOX_TEST_V1"
    _write_variant_fixture(tmp_path, reject_variant, candidate_allowed=False, recommendation="Reject")
    _write_variant_fixture(tmp_path, data_blocked_variant, candidate_allowed=False, recommendation="Watch", metrics_status="BLOCKED")

    rejected = add_to_paper_sandbox(tmp_path, RUN_ID, reject_variant, user_confirmation=True)
    assert rejected["ok"] is False
    assert rejected["state"] == "SANDBOX_BLOCKED"
    assert "Reject/Blocked" in rejected["message"]
    assert not (
        tmp_path
        / "output"
        / "strategy_factory"
        / "sandbox"
        / sandbox_id_for(RUN_ID, reject_variant)
        / "sandbox_admission.json"
    ).exists()

    blocked = add_to_paper_sandbox(tmp_path, RUN_ID, data_blocked_variant, user_confirmation=True)
    assert blocked["ok"] is False
    assert blocked["state"] == "SANDBOX_BLOCKED"
    assert "Blocked data/backtest evidence" in blocked["message"]


def test_synthetic_eligible_variant_full_admission_artifact_flow(tmp_path: Path) -> None:
    _write_variant_fixture(
        tmp_path,
        ELIGIBLE_VARIANT,
        candidate_allowed=True,
        synthetic=True,
        proxy_only=False,
        evidence_score=82,
    )
    candidate_id = candidate_id_for(RUN_ID, ELIGIBLE_VARIANT)
    admission_dir = tmp_path / "output" / "strategy_factory" / "admission" / candidate_id

    added = add_candidate(tmp_path, RUN_ID, ELIGIBLE_VARIANT, target_weight=0.03)
    assert added["ok"] is True
    assert added["state"] == "IN_CANDIDATE_PORTFOLIO"
    assert (admission_dir / "candidate_admission.json").exists()
    assert (admission_dir / "candidate_portfolio_entry.json").exists()
    assert _read_json(admission_dir / "candidate_admission.json", {})["synthetic_admission_test_only"] is True

    risk = run_risk_review(tmp_path, RUN_ID, ELIGIBLE_VARIANT)
    assert risk["ok"] is True
    assert risk["risk_review"]["status"] == "PASS"
    assert risk["state"] == "RISK_REVIEW_PASSED"
    assert risk["artifacts"]["allocation_draft.json"] is None
    assert (admission_dir / "risk_review.json").exists()
    assert (admission_dir / "transaction_cost_estimate.json").exists()
    assert (admission_dir / "risk_impact_estimate.json").exists()

    draft = generate_allocation_draft(tmp_path, RUN_ID, ELIGIBLE_VARIANT, target_weight=0.04)
    assert draft["ok"] is True
    assert draft["artifacts"]["allocation_draft.json"].endswith("allocation_draft.json")
    allocation = _read_json(admission_dir / "allocation_draft.json", {})
    assert allocation["target_weight"] == 0.03
    assert "transaction_cost_estimate" in allocation
    assert "risk_impact_estimate" in allocation
    assert draft["state"] == "AWAITING_USER_CONFIRMATION"

    try:
        apply_to_paper(tmp_path, RUN_ID, ELIGIBLE_VARIANT, user_confirmation=False)
    except ValueError as exc:
        assert "explicit user_confirmation=true required" in str(exc)
    else:
        raise AssertionError("paper apply should require explicit confirmation")
    assert not (admission_dir / "paper_apply_confirmation.json").exists()

    applied = apply_to_paper(tmp_path, RUN_ID, ELIGIBLE_VARIANT, user_confirmation=True)
    assert applied["ok"] is True
    assert applied["state"] == "PAPER_APPLIED"
    assert (admission_dir / "paper_apply_confirmation.json").exists()
    assert (admission_dir / "paper_strategy_sleeve.json").exists()
    assert (admission_dir / "combined_recompute_request.json").exists()
    assert (admission_dir / "strategy_monitor_target.json").exists()
    assert (admission_dir / "allocation_rebalance_target.json").exists()
    assert (admission_dir / "portfolio_pnl_target.json").exists()
    assert (admission_dir / "risk_contribution_target.json").exists()
    assert (admission_dir / "correlation_target.json").exists()
    assert (admission_dir / "downstream_refresh_targets.json").exists()
    assert (admission_dir / "downstream_integration_status.json").exists()

    sleeve = _read_json(admission_dir / "paper_strategy_sleeve.json", {})
    assert sleeve["strategy_id"].startswith("SF_STRATEGY_")
    assert sleeve["sleeve_id"].startswith("PAPER_SLEEVE_")
    assert sleeve["source_run_id"] == RUN_ID
    assert sleeve["variant_id"] == ELIGIBLE_VARIANT
    assert sleeve["target_weight"] == 0.03
    assert sleeve["paper_only"] is True
    assert sleeve["live_trading"] is False
    assert sleeve["effective_date"]
    assert "transaction_cost_estimate" in sleeve
    assert sleeve["allocation_delta"] == {candidate_id: 0.03}
    assert sleeve["combined_recompute_required"] is True
    assert sleeve["synthetic_admission_test_only"] is True

    downstream = _read_json(admission_dir / "downstream_integration_status.json", {})
    assert downstream["strategy_monitor"] == "PENDING_NEXT_PAPER_REFRESH"
    assert downstream["allocation"] == "PENDING_NEXT_PAPER_REFRESH"
    assert downstream["risk"] == "PENDING_RISK_RECALCULATION"
    assert downstream["correlation"] == "PENDING_NEXT_PAPER_REFRESH"
    assert downstream["portfolio_nav_pnl"] == "PENDING_NEXT_PAPER_REFRESH"
    assert downstream["combined"] == "PENDING_COMBINED_RECOMPUTE"
    assert downstream["combined_recompute_required"] is True
    assert _read_json(admission_dir / "portfolio_pnl_target.json", {})["nav_pnl_fabricated"] is False
    refresh_targets = _read_json(admission_dir / "downstream_refresh_targets.json", {})
    assert refresh_targets["targets"]["Risk Contribution"] == "PENDING_RISK_RECALCULATION"
    assert refresh_targets["targets"]["Portfolio NAV/P&L"] == "PENDING_NEXT_PAPER_REFRESH"

    for artifact in admission_dir.glob("*.json"):
        _assert_no_true_live_trading(_read_json(artifact, {}))
    status = get_admission_status(tmp_path, RUN_ID, ELIGIBLE_VARIANT)
    assert status["state"] == "PAPER_APPLIED"
    assert status["downstream_refresh_status"]["combined"] == "PENDING_COMBINED_RECOMPUTE"
    assert not (tmp_path / "dashboard" / "data" / "canonical_operational.json").exists()


def test_admission_endpoints_and_confirmation_gate(tmp_path: Path) -> None:
    _write_variant_fixture(
        tmp_path,
        ELIGIBLE_VARIANT,
        candidate_allowed=True,
        synthetic=True,
        proxy_only=False,
        evidence_score=82,
    )

    class TmpRootHandler(WorkstationHandler):
        server_root = tmp_path

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    server = ThreadingHTTPServer(("127.0.0.1", port), TmpRootHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def post(path: str, body: dict) -> dict:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        body = {"run_id": RUN_ID, "variant_id": ELIGIBLE_VARIANT, "target_weight": 0.02}
        assert post("/api/strategy-factory/admission/add-candidate", body)["state"] == "IN_CANDIDATE_PORTFOLIO"
        assert post("/api/strategy-factory/admission/run-risk-review", body)["state"] == "RISK_REVIEW_PASSED"
        assert post("/api/strategy-factory/admission/generate-allocation-draft", body)["state"] == "AWAITING_USER_CONFIRMATION"
        try:
            post("/api/strategy-factory/admission/apply-to-paper", {**body, "user_confirmation": False})
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            error_payload = json.loads(exc.read().decode("utf-8"))
            assert "explicit user_confirmation=true required" in error_payload["error"]
        else:
            raise AssertionError("endpoint should reject paper apply without confirmation")
        applied = post("/api/strategy-factory/admission/apply-to-paper", {**body, "user_confirmation": True})
        assert applied["state"] == "PAPER_APPLIED"
        assert applied["paper_strategy_sleeve"]["live_trading"] is False
        assert applied["paper_strategy_sleeve"]["combined_recompute_required"] is True
        assert applied["combined_recompute_request"]["brokerage_execution"] is False
        assert applied["combined_recompute_request"]["status"] == "PENDING_COMBINED_RECOMPUTE"
        assert applied["downstream_refresh_status"]["portfolio_nav_pnl"] == "PENDING_NEXT_PAPER_REFRESH"
    finally:
        server.shutdown()


def test_paper_sandbox_endpoint_and_confirmation_gate(tmp_path: Path) -> None:
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, evidence_score=58)

    class TmpRootHandler(WorkstationHandler):
        server_root = tmp_path

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    server = ThreadingHTTPServer(("127.0.0.1", port), TmpRootHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def post(path: str, body: dict) -> dict:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        body = {"run_id": RUN_ID, "variant_id": BLOCKED_VARIANT, "target_weight": 0.02}
        try:
            post("/api/strategy-factory/sandbox/add", {**body, "user_confirmation": False})
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            error_payload = json.loads(exc.read().decode("utf-8"))
            assert "explicit user_confirmation=true required" in error_payload["error"]
        else:
            raise AssertionError("sandbox endpoint should reject without confirmation")

        result = post("/api/strategy-factory/sandbox/add", {**body, "user_confirmation": True})
        assert result["state"] == "SANDBOX_MONITORING"
        assert result["sandbox_paper_sleeve"]["paper_only"] is True
        assert result["sandbox_paper_sleeve"]["live_trading"] is False
        assert result["sandbox_paper_sleeve"]["target_weight"] <= 0.01
        assert result["sandbox_monitoring_status"]["downstream_targets"]["Combined Strategy"] == "PENDING_COMBINED_RECOMPUTE"
    finally:
        server.shutdown()


def test_portfolio_candidate_requires_confirmation_and_does_not_create_candidate(tmp_path: Path) -> None:
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Watch")
    candidate_id = candidate_id_for(RUN_ID, BLOCKED_VARIANT)

    try:
        add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=False)
    except ValueError as exc:
        assert "explicit user_confirmation=true required" in str(exc)
    else:
        raise AssertionError("portfolio candidate add should require explicit confirmation")

    candidate_path = tmp_path / "output" / "strategy_factory" / "portfolio_candidates" / candidate_id / "portfolio_candidate.json"
    assert not candidate_path.exists()


def test_legacy_unconfirmed_portfolio_record_does_not_show_as_active(tmp_path: Path) -> None:
    candidate_id = candidate_id_for(RUN_ID, BLOCKED_VARIANT)
    candidate_dir = tmp_path / "output" / "strategy_factory" / "portfolio_candidates" / candidate_id
    _write_json(
        candidate_dir / "portfolio_candidate.json",
        {
            "candidate_id": candidate_id,
            "run_id": RUN_ID,
            "variant_id": BLOCKED_VARIANT,
            "strategy_name": "Legacy unconfirmed record",
            "status": "ACTIVE_UNALLOCATED",
            "state": "ACTIVE_UNALLOCATED",
            "user_confirmed": False,
            "active_strategy": True,
            "current_weight": 0.0,
            "target_weight": 0.0,
            "live_trading": False,
            "brokerage_execution": False,
        },
    )
    _write_json(
        candidate_dir / "activation_record.json",
        {
            "candidate_id": candidate_id,
            "display_id": "#000018",
            "status": "ACTIVE_UNALLOCATED",
            "user_confirmed": False,
            "current_weight": 0.0,
            "target_weight": 0.0,
            "live_trading": False,
            "brokerage_execution": False,
        },
    )

    status = get_portfolio_candidates_status(tmp_path, RUN_ID, BLOCKED_VARIANT)

    assert status["state"] == "PENDING_USER_APPROVAL"
    assert status["selected"]["pending_user_approval"] is True
    assert status["selected"]["active_strategy"] is False
    assert status["candidate_count"] == 0
    assert status["active_unallocated_count"] == 0
    assert status["watchlist"] == []
    assert status["active_unallocated"] == []


def test_watch_variant_with_candidate_allowed_false_enters_portfolio_candidates_only(tmp_path: Path) -> None:
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Watch")

    result = add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)
    candidate = result["candidate"]

    assert result["ok"] is True
    assert result["state"] == "IN_PORTFOLIO_CANDIDATES"
    assert candidate["status"] == "IN_PORTFOLIO_CANDIDATES"
    assert candidate["candidate_allowed"] is False
    assert candidate["simulated"] is True
    assert candidate["live_trading"] is False
    assert candidate["brokerage_execution"] is False
    assert candidate["current_weight"] == 0.0
    assert candidate["target_weight"] == 0.0
    assert candidate["recommended_weight"] == "RECOMMENDATION_PENDING"
    assert candidate["active_strategy"] is False
    assert result["selected"]["candidate_id"] == candidate_id_for(RUN_ID, BLOCKED_VARIANT)
    assert result["active_unallocated_count"] == 0
    assert result["candidate_count"] == 1
    assert result["selected"]["artifacts"]["portfolio_candidate.json"].endswith("portfolio_candidate.json")
    assert result["selected"]["artifacts"]["activation_record.json"] is None
    assert candidate["user_confirmed_at"]
    assert candidate["user_action_id"]


def test_portfolio_candidate_activation_requires_candidate_and_confirmation(tmp_path: Path) -> None:
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Modify")

    try:
        activate_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)
    except ValueError as exc:
        assert "portfolio candidate artifact required" in str(exc)
    else:
        raise AssertionError("activation should require an existing portfolio candidate")

    add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)
    try:
        activate_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=False)
    except ValueError as exc:
        assert "explicit user_confirmation=true required" in str(exc)
    else:
        raise AssertionError("activation should require explicit confirmation")


def test_confirmed_portfolio_candidate_activation_creates_active_unallocated(tmp_path: Path) -> None:
    _write_canonical_display_ids(tmp_path, 17)
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Modify")
    add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)

    result = activate_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)
    activation = result["activation"]

    assert result["ok"] is True
    assert result["state"] == "ACTIVE_UNALLOCATED"
    assert activation["display_id"] == "#000018"
    assert activation["display_label"] == "#000018"
    assert activation["strategy_uid"].startswith("SF_STRATEGY_UID_")
    assert activation["strategy_uid"] != activation["display_label"]
    assert activation["strategy_id"] == activation["strategy_uid"]
    assert activation["status"] == "ACTIVE_UNALLOCATED"
    assert activation["user_confirmed_at"]
    assert activation["activation_confirmed_at"]
    assert activation["user_action_id"]
    assert activation["activation_source"] == "USER_UI"
    assert activation["activation_confirmation"] is True
    assert activation["TEST_ARTIFACT"] is False
    assert activation["SMOKE_ONLY"] is False
    assert activation["EXCLUDE_FROM_ACTIVE_UNIVERSE"] is False
    assert activation["current_weight"] == 0.0
    assert activation["target_weight"] == 0.0
    assert activation["recommended_weight"] == "RECOMMENDATION_PENDING"
    assert activation["eligible_for_optimizer"] is True
    assert activation["eligible_for_rebalance"] is True
    assert activation["simulated"] is True
    assert activation["live_trading"] is False
    assert activation["brokerage_execution"] is False
    assert activation["nav_pnl_impact"] == "NONE_WHILE_CURRENT_WEIGHT_ZERO"
    assert result["active_unallocated_count"] == 1
    assert result["candidate_count"] == 0
    assert result["selected"]["status"] == "ACTIVE_UNALLOCATED"
    assert result["selected"]["display_label"] == "#000018"
    assert result["selected"]["strategy_uid"] == activation["strategy_uid"]
    assert result["selected"]["strategy_id"] == activation["strategy_uid"]
    assert result["selected"]["current_weight"] == 0.0
    assert result["selected"]["target_weight"] == 0.0
    durable_dir = (
        tmp_path
        / "data"
        / "strategy_factory"
        / "portfolio_candidates"
        / candidate_id_for(RUN_ID, BLOCKED_VARIANT)
    )
    durable_activation = json.loads((durable_dir / "activation_record.json").read_text(encoding="utf-8"))
    durable_candidate = json.loads((durable_dir / "portfolio_candidate.json").read_text(encoding="utf-8"))
    assert durable_activation["strategy_uid"] == activation["strategy_uid"]
    assert durable_activation["activation_source"] == "USER_UI"
    assert durable_activation["activation_confirmation"] is True
    assert durable_activation["current_weight"] == 0.0
    assert durable_activation["target_weight"] == 0.0
    assert durable_activation["live_trading"] is False
    assert durable_activation["brokerage_execution"] is False
    assert durable_candidate["strategy_uid"] == activation["strategy_uid"]

    status = get_portfolio_candidates_status(tmp_path, RUN_ID, BLOCKED_VARIANT)
    assert status["state"] == "ACTIVE_UNALLOCATED"
    assert status["selected"]["activation"]["display_id"] == "#000018"
    assert status["selected"]["display_label"] == "#000018"
    assert status["selected"]["strategy_uid"] == activation["strategy_uid"]
    assert not (tmp_path / "output" / "paper_ledger.json").exists()
    assert not (tmp_path / "output" / "combined").exists()


def test_smoke_activation_is_pending_and_excluded_from_active_universe(tmp_path: Path) -> None:
    _write_canonical_display_ids(tmp_path, 17)
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Modify")
    add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True, user_action_id="TEST_ACCEPT")

    result = activate_portfolio_candidate(
        tmp_path,
        RUN_ID,
        BLOCKED_VARIANT,
        user_confirmation=True,
        user_action_id="SMOKE_ACTION",
        activation_source="SMOKE_TEST",
        smoke_only=True,
    )

    activation = result["activation"]
    assert activation["display_id"] == "#000018"
    assert activation["display_label"] == "#000018"
    assert activation["strategy_uid"] != activation["display_label"]
    assert activation["status"] == "PENDING_USER_APPROVAL"
    assert activation["TEST_ARTIFACT"] is True
    assert activation["SMOKE_ONLY"] is True
    assert activation["EXCLUDE_FROM_ACTIVE_UNIVERSE"] is True
    assert activation["activation_confirmation"] is False
    assert activation["activation_confirmed_at"] is None
    assert result["active_unallocated_count"] == 0
    assert result["pending_approval_count"] == 1
    assert result["selected"]["status"] == "PENDING_USER_APPROVAL"
    assert result["selected"]["display_label"] == "#000018"
    assert result["selected"]["strategy_uid"] == activation["strategy_uid"]
    assert result["selected"]["current_weight"] == 0.0
    assert result["selected"]["target_weight"] == 0.0
    assert result["selected"]["nav_pnl_impact"] == "NONE_PENDING_USER_APPROVAL"


def test_combined_row_does_not_consume_ordinary_display_label_or_active_count(tmp_path: Path) -> None:
    _write_canonical_display_ids(tmp_path, 16, include_combined=True)
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Modify")
    add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)

    result = activate_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)
    activation = result["activation"]

    assert activation["display_id"] == "#000017"
    assert activation["display_label"] == "#000017"
    assert result["ordinary_active_count_before"] == 16
    assert result["combined_active_count_before"] == 1
    assert result["top_level_active_count_before"] == 17
    assert result["ordinary_active_count_after"] == 17
    assert result["combined_active_count_after"] == 1
    assert result["top_level_active_count_after"] == 18
    assert result["next_ordinary_display_label_after_approval"] == "#000017"
    assert result["ordinary_active_count"] == 17
    assert result["combined_active_count"] == 1
    assert result["top_level_active_count"] == 18

    status = get_portfolio_candidates_status(tmp_path, RUN_ID, BLOCKED_VARIANT)
    assert status["ordinary_active_count"] == 17
    assert status["combined_active_count"] == 1
    assert status["top_level_active_count"] == 18


def test_pending_approval_does_not_change_combined_or_ordinary_active_counts(tmp_path: Path) -> None:
    _write_canonical_display_ids(tmp_path, 16, include_combined=True)
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Modify")
    add_portfolio_candidate(tmp_path, RUN_ID, BLOCKED_VARIANT, user_confirmation=True)

    result = activate_portfolio_candidate(
        tmp_path,
        RUN_ID,
        BLOCKED_VARIANT,
        user_confirmation=True,
        user_action_id="SMOKE_ACTION",
        activation_source="SMOKE_TEST",
        smoke_only=True,
    )

    assert result["activation"]["status"] == "PENDING_USER_APPROVAL"
    assert result["ordinary_active_count_before"] == 16
    assert result["combined_active_count_before"] == 1
    assert result["top_level_active_count_before"] == 17
    assert result["ordinary_active_count_after"] == 16
    assert result["combined_active_count_after"] == 1
    assert result["top_level_active_count_after"] == 17
    assert result["ordinary_active_count"] == 16
    assert result["combined_active_count"] == 1
    assert result["top_level_active_count"] == 17
    assert result["pending_approval_count"] == 1
    assert result["active_unallocated_count"] == 0

    approved = activate_portfolio_candidate(
        tmp_path,
        RUN_ID,
        BLOCKED_VARIANT,
        user_confirmation=True,
        user_action_id="USER_UI_MONITOR_APPROVE",
        activation_source="USER_UI",
    )
    activation = approved["activation"]
    assert activation["status"] == "ACTIVE_UNALLOCATED"
    assert activation["user_confirmed_at"]
    assert activation["activation_confirmed_at"]
    assert activation["user_action_id"] == "USER_UI_MONITOR_APPROVE"
    assert activation["activation_source"] == "USER_UI"
    assert activation["activation_confirmation"] is True
    assert activation["current_weight"] == 0.0
    assert activation["target_weight"] == 0.0
    assert activation["eligible_for_rebalance"] is True
    assert activation["eligible_for_optimizer"] is True
    assert activation["live_trading"] is False
    assert activation["brokerage_execution"] is False
    assert approved["ordinary_active_count"] == 17
    assert approved["combined_active_count"] == 1
    assert approved["top_level_active_count"] == 18
    assert approved["pending_approval_count"] == 0
    assert approved["active_unallocated_count"] == 1
    assert not (tmp_path / "output" / "paper_ledger.json").exists()
    assert not (tmp_path / "dashboard" / "data" / "performance" / "paper_portfolio_daily.json").exists()


def test_pending_000020_can_be_user_approved_without_changing_id(tmp_path: Path) -> None:
    variant_id = "US_STOCK_LOW_VOL_63D_TOP20_V1"
    _write_canonical_display_ids(tmp_path, 19)
    _write_variant_fixture(tmp_path, variant_id, candidate_allowed=False, synthetic=True, proxy_only=False, evidence_score=64, recommendation="Watch")
    add_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True, user_action_id="TEST_ACCEPT_LOW_VOL")
    pending = activate_portfolio_candidate(
        tmp_path,
        RUN_ID,
        variant_id,
        user_confirmation=True,
        user_action_id="SMOKE_LOW_VOL",
        activation_source="SMOKE_TEST",
        smoke_only=True,
    )
    assert pending["activation"]["display_id"] == "#000020"
    assert pending["activation"]["display_label"] == "#000020"
    assert pending["activation"]["strategy_uid"] != "#000020"
    assert pending["active_unallocated_count"] == 0
    assert pending["pending_approval_count"] == 1
    assert pending["selected"]["display_label"] == "#000020"
    assert pending["selected"]["strategy_uid"] == pending["activation"]["strategy_uid"]

    approved = activate_portfolio_candidate(
        tmp_path,
        RUN_ID,
        variant_id,
        user_confirmation=True,
        user_action_id="USER_APPROVE_000020",
        activation_source="USER_UI",
    )

    assert approved["activation"]["display_id"] == "#000020"
    assert approved["activation"]["display_label"] == "#000020"
    assert approved["activation"]["strategy_uid"] == pending["activation"]["strategy_uid"]
    assert approved["activation"]["strategy_uid"] != approved["activation"]["display_label"]
    assert approved["activation"]["status"] == "ACTIVE_UNALLOCATED"
    assert approved["activation"]["activation_confirmation"] is True
    assert approved["active_unallocated_count"] == 1
    assert approved["selected"]["status"] == "ACTIVE_UNALLOCATED"
    assert approved["selected"]["display_label"] == "#000020"
    assert approved["selected"]["strategy_uid"] == approved["activation"]["strategy_uid"]


def test_etf_watch_variant_accepts_and_activates_without_fake_nav_pnl(tmp_path: Path) -> None:
    variant_id = "ETF_ROTATION_63_126_TOP2_V1"
    _write_canonical_display_ids(tmp_path, 17)
    _write_variant_fixture(
        tmp_path,
        variant_id,
        candidate_allowed=False,
        synthetic=True,
        proxy_only=False,
        evidence_score=61,
        recommendation="Watch",
    )
    variant_dir = tmp_path / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    spec = _read_json(variant_dir / "variant_spec.json", {})
    spec.update(
        {
            "theme": "etf_momentum_rotation",
            "strategy_name": "ETF Momentum Rotation 63/126 Top 2",
            "variant_name": "ETF Momentum Rotation 63/126 Top 2",
            "thesis": "Cross-asset ETF momentum rotation fixture thesis.",
            "signal_formula": "Rank SPY, QQQ, IWM, EFA, EEM, TLT, GLD by 63d plus 126d momentum monthly; hold top 2.",
            "universe_or_proxy": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
            "benchmark": "SPY",
            "data_requirements": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
        }
    )
    _write_json(variant_dir / "variant_spec.json", spec)
    ml_path = variant_dir / "evaluation" / "variant_ml_diagnostics_run.json"
    _write_json(ml_path, {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available"})

    added = add_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True)
    activated = activate_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True)

    assert added["state"] == "IN_PORTFOLIO_CANDIDATES"
    assert added["candidate"]["theme"] == "etf_momentum_rotation"
    assert added["candidate"]["strategy_name"] == "ETF Momentum Rotation 63/126 Top 2"
    assert added["candidate"]["evidence_metrics"]["ml_summary"] == "BLOCKED"
    activation = activated["activation"]
    assert activation["display_id"] == "#000018"
    assert activation["strategy_name"] == "ETF Momentum Rotation 63/126 Top 2"
    assert activation["current_weight"] == 0.0
    assert activation["target_weight"] == 0.0
    assert activation["eligible_for_rebalance"] is True
    assert activation["live_trading"] is False
    assert activation["brokerage_execution"] is False
    assert activation["nav_pnl_impact"] == "NONE_WHILE_CURRENT_WEIGHT_ZERO"
    assert not (tmp_path / "output" / "paper_ledger.json").exists()
    assert not (tmp_path / "dashboard" / "data" / "performance" / "paper_portfolio_daily.json").exists()


def test_us_stock_watch_variant_accepts_and_activates_without_fake_nav_pnl(tmp_path: Path) -> None:
    variant_id = "US_STOCK_MOMENTUM_12_1_TOP50_V1"
    _write_canonical_display_ids(tmp_path, 17)
    _write_variant_fixture(
        tmp_path,
        variant_id,
        candidate_allowed=False,
        synthetic=True,
        proxy_only=False,
        evidence_score=62,
        recommendation="Watch",
    )
    variant_dir = tmp_path / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    spec = _read_json(variant_dir / "variant_spec.json", {})
    spec.update(
        {
            "theme": "us_stock_cross_sectional_momentum_quality",
            "strategy_name": "U.S. Stock Momentum 12-1 Top 50",
            "variant_name": "U.S. Stock Momentum 12-1 Top 50",
            "thesis": "U.S. stock cross-sectional momentum fixture thesis.",
            "signal_formula": "Rank U.S. stocks by 252d momentum excluding the most recent 21 trading days; hold top basket.",
            "universe_or_proxy": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG"],
            "benchmark": "SPY",
            "data_requirements": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "SPY"],
        }
    )
    _write_json(variant_dir / "variant_spec.json", spec)
    ml_path = variant_dir / "evaluation" / "variant_ml_diagnostics_run.json"
    _write_json(ml_path, {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available"})

    added = add_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True)
    activated = activate_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True)

    assert added["state"] == "IN_PORTFOLIO_CANDIDATES"
    assert added["candidate"]["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert added["candidate"]["strategy_name"] == "U.S. Stock Momentum 12-1 Top 50"
    activation = activated["activation"]
    assert activation["display_id"] == "#000018"
    assert activation["strategy_name"] == "U.S. Stock Momentum 12-1 Top 50"
    assert activation["current_weight"] == 0.0
    assert activation["target_weight"] == 0.0
    assert activation["eligible_for_rebalance"] is True
    assert activation["live_trading"] is False
    assert activation["brokerage_execution"] is False
    assert activation["nav_pnl_impact"] == "NONE_WHILE_CURRENT_WEIGHT_ZERO"
    assert not (tmp_path / "output" / "paper_ledger.json").exists()
    assert not (tmp_path / "dashboard" / "data" / "performance" / "paper_portfolio_daily.json").exists()


def test_low_vol_defensive_watch_variant_accepts_and_activates_without_fake_nav_pnl(tmp_path: Path) -> None:
    variant_id = "US_STOCK_LOW_VOL_63D_TOP20_V1"
    _write_canonical_display_ids(tmp_path, 17)
    _write_variant_fixture(
        tmp_path,
        variant_id,
        candidate_allowed=False,
        synthetic=True,
        proxy_only=False,
        evidence_score=64,
        recommendation="Watch",
    )
    variant_dir = tmp_path / "output" / "strategy_factory" / "runs" / RUN_ID / "variants" / variant_id
    spec = _read_json(variant_dir / "variant_spec.json", {})
    spec.update(
        {
            "theme": "us_stock_low_vol_defensive",
            "strategy_name": "U.S. Stock Low Vol Defensive 63D Top 20",
            "variant_name": "U.S. Stock Low Vol 63D Top 20",
            "thesis": "U.S. stock low-vol defensive fixture thesis.",
            "signal_formula": "Rank U.S. stocks by lower 63d realized volatility; hold top defensive basket.",
            "universe_or_proxy": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG"],
            "benchmark": "SPY",
            "data_requirements": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "SPY"],
        }
    )
    _write_json(variant_dir / "variant_spec.json", spec)
    ml_path = variant_dir / "evaluation" / "variant_ml_diagnostics_run.json"
    _write_json(ml_path, {"status": "BLOCKED", "ml_evidence_status": "MISSING_EVIDENCE", "reason": "No ML evidence available for U.S. Stock Low Vol Defensive"})

    added = add_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True)
    activated = activate_portfolio_candidate(tmp_path, RUN_ID, variant_id, user_confirmation=True)

    assert added["state"] == "IN_PORTFOLIO_CANDIDATES"
    assert added["candidate"]["theme"] == "us_stock_low_vol_defensive"
    assert added["candidate"]["strategy_name"] == "U.S. Stock Low Vol Defensive 63D Top 20"
    activation = activated["activation"]
    assert activation["display_id"] == "#000018"
    assert activation["strategy_name"] == "U.S. Stock Low Vol Defensive 63D Top 20"
    assert activation["current_weight"] == 0.0
    assert activation["target_weight"] == 0.0
    assert activation["eligible_for_rebalance"] is True
    assert activation["live_trading"] is False
    assert activation["brokerage_execution"] is False
    assert activation["nav_pnl_impact"] == "NONE_WHILE_CURRENT_WEIGHT_ZERO"
    assert not (tmp_path / "output" / "paper_ledger.json").exists()
    assert not (tmp_path / "dashboard" / "data" / "performance" / "paper_portfolio_daily.json").exists()


def test_portfolio_candidate_reject_and_data_blocked_variants_are_blocked(tmp_path: Path) -> None:
    reject_variant = "REJECTED_PORTFOLIO_CANDIDATE_TEST_V1"
    data_blocked_variant = "DATA_BLOCKED_PORTFOLIO_CANDIDATE_TEST_V1"
    _write_variant_fixture(tmp_path, reject_variant, candidate_allowed=False, recommendation="Reject")
    _write_variant_fixture(tmp_path, data_blocked_variant, candidate_allowed=False, recommendation="Watch", metrics_status="BLOCKED")

    rejected = add_portfolio_candidate(tmp_path, RUN_ID, reject_variant, user_confirmation=True)
    assert rejected["ok"] is False
    assert rejected["state"] == "PORTFOLIO_CANDIDATE_BLOCKED"
    assert "Reject/Blocked" in rejected["reason"]
    assert not (
        tmp_path
        / "output"
        / "strategy_factory"
        / "portfolio_candidates"
        / candidate_id_for(RUN_ID, reject_variant)
        / "portfolio_candidate.json"
    ).exists()

    blocked = add_portfolio_candidate(tmp_path, RUN_ID, data_blocked_variant, user_confirmation=True)
    assert blocked["ok"] is False
    assert blocked["state"] == "PORTFOLIO_CANDIDATE_BLOCKED"
    assert "Data-blocked" in blocked["reason"]


def test_portfolio_candidate_next_id_increments_from_canonical_and_local_records(tmp_path: Path) -> None:
    _write_canonical_display_ids(tmp_path, 17)
    first_variant = "FIRST_MODIFY_PORTFOLIO_CANDIDATE_TEST_V1"
    second_variant = "SECOND_WATCH_PORTFOLIO_CANDIDATE_TEST_V1"
    _write_variant_fixture(tmp_path, first_variant, candidate_allowed=False, recommendation="Modify")
    _write_variant_fixture(tmp_path, second_variant, candidate_allowed=False, recommendation="Watch")

    add_portfolio_candidate(tmp_path, RUN_ID, first_variant, user_confirmation=True)
    first = activate_portfolio_candidate(tmp_path, RUN_ID, first_variant, user_confirmation=True)["activation"]
    add_portfolio_candidate(tmp_path, RUN_ID, second_variant, user_confirmation=True)
    second = activate_portfolio_candidate(tmp_path, RUN_ID, second_variant, user_confirmation=True)["activation"]

    assert first["display_id"] == "#000018"
    assert second["display_id"] == "#000019"
    assert second["current_weight"] == 0.0
    assert second["target_weight"] == 0.0
    assert second["live_trading"] is False
    assert second["brokerage_execution"] is False


def test_portfolio_candidate_endpoints_and_confirmation_gate(tmp_path: Path) -> None:
    _write_canonical_display_ids(tmp_path, 17)
    _write_variant_fixture(tmp_path, BLOCKED_VARIANT, candidate_allowed=False, proxy_only=True, recommendation="Watch")

    class TmpRootHandler(WorkstationHandler):
        server_root = tmp_path

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    server = ThreadingHTTPServer(("127.0.0.1", port), TmpRootHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def post(path: str, body: dict) -> dict:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        body = {"run_id": RUN_ID, "variant_id": BLOCKED_VARIANT}
        try:
            post("/api/strategy-factory/portfolio-candidates/add", {**body, "user_confirmation": False})
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            error_payload = json.loads(exc.read().decode("utf-8"))
            assert "explicit user_confirmation=true required" in error_payload["error"]
        else:
            raise AssertionError("portfolio candidate endpoint should reject without confirmation")

        added = post("/api/strategy-factory/portfolio-candidates/add", {**body, "user_confirmation": True})
        assert added["state"] == "IN_PORTFOLIO_CANDIDATES"
        assert added["selected"]["active_strategy"] is False
        assert added["selected"]["candidate_allowed"] is False

        try:
            post("/api/strategy-factory/portfolio-candidates/activate", {**body, "user_confirmation": False})
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            error_payload = json.loads(exc.read().decode("utf-8"))
            assert "explicit user_confirmation=true required" in error_payload["error"]
        else:
            raise AssertionError("activation endpoint should reject without confirmation")

        activated = post("/api/strategy-factory/portfolio-candidates/activate", {**body, "user_confirmation": True})
        assert activated["state"] == "ACTIVE_UNALLOCATED"
        assert activated["activation"]["display_id"] == "#000018"
        assert activated["activation"]["current_weight"] == 0.0
        assert activated["activation"]["target_weight"] == 0.0
        assert activated["activation"]["live_trading"] is False
        assert activated["activation"]["brokerage_execution"] is False

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/strategy-factory/portfolio-candidates/status?run_id={RUN_ID}&variant_id={BLOCKED_VARIANT}",
            timeout=10,
        ) as response:
            status = json.loads(response.read().decode("utf-8"))
        assert status["state"] == "ACTIVE_UNALLOCATED"
        assert status["selected"]["activation"]["display_id"] == "#000018"
    finally:
        server.shutdown()
