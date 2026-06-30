from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.automation.paper_allocation_proposal import build_paper_allocation_proposal
from src.automation.paper_allocation_report import write_paper_allocation_report
from src.automation.strategy_factory_selected_batch_job import run_selected_batch_job


def _cards() -> dict:
    return {
        "ok": True,
        "cards": [
            {
                "strategy_uid": "test-composite",
                "strategy_name": "Test Composite",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "executed",
                "current_weight": 0.2,
                "research_decision": "RESEARCH_COMPOSITE_CONSTRUCTED",
                "daily_recommendation": {
                    "recommended_action": "HOLD",
                    "reason": "Test-only composite reason.",
                    "evidence_strength": "PARTIAL",
                },
            },
            {
                "strategy_uid": "test-active-a",
                "strategy_name": "Test Active A",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "executed",
                "current_weight": 0.5,
                "strategy_role": "ORDINARY",
                "sleeve_type": "TOP_LEVEL",
                "daily_recommendation": {
                    "recommended_action": "HOLD",
                    "reason": "Test-only hold reason.",
                    "evidence_strength": "PARTIAL",
                },
                "ml_role": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
            },
            {
                "strategy_uid": "test-active-b",
                "strategy_name": "Test Active B",
                "source_status": "CANONICAL_OPERATIONAL",
                "portfolio_status": "executed",
                "current_weight": 0.3,
                "strategy_role": "ORDINARY",
                "sleeve_type": "TOP_LEVEL",
                "daily_recommendation": {
                    "recommended_action": "REVIEW",
                    "reason": "Test-only review reason.",
                    "evidence_strength": "MISSING",
                },
                "ml_role": "ML_MISSING_EVIDENCE",
                "return_attribution_summary": {"status": "Missing Attribution Evidence"},
            },
            {
                "strategy_uid": "test-candidate",
                "strategy_name": "Test Candidate",
                "source_status": "STRATEGY_FACTORY_ACTIVATION_RECORD",
                "portfolio_status": "ACTIVE_UNALLOCATED",
                "current_weight": 0.0,
                "strategy_role": "RESEARCH",
                "sleeve_type": "PAPER_REVIEW_CANDIDATE",
                "decision_recommendation": "ACTIVE_UNALLOCATED_ZERO_WEIGHT",
                "daily_recommendation": {
                    "recommended_action": "REVIEW",
                    "reason": "Test-only candidate review reason.",
                    "evidence_strength": "PARTIAL",
                },
                "ml_role": "ML_MISSING_EVIDENCE",
                "source_artifacts": [
                    {
                        "kind": "strategy_factory_activation",
                        "path": "test-only/activation_record.json",
                        "status": "USER_CONFIRMED_LOCAL_ARTIFACT",
                    }
                ],
            },
        ],
    }


def test_paper_allocation_proposal_sums_to_100_and_adds_candidate_target(tmp_path: Path) -> None:
    payload = build_paper_allocation_proposal(
        tmp_path,
        now=datetime(2026, 6, 29, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    assert payload["source"] == "paper_allocation_proposal_v1"
    assert payload["proposal_cycle"] == "BIWEEKLY"
    assert payload["next_scheduled_proposal_date"] == "2026-07-13"
    assert payload["sums_to_100pct"] is True
    assert abs(payload["target_weight_sum"] - 1.0) <= payload["weight_sum_tolerance"]
    candidate = next(row for row in payload["rows"] if row["strategy_uid"] == "test-candidate")
    composite = next(row for row in payload["rows"] if row["strategy_uid"] == "test-composite")
    assert candidate["current_weight"] == 0.0
    assert candidate["suggested_weight"] == 0.02
    assert candidate["target_weight"] == candidate["suggested_weight"]
    assert candidate["suggested_action"] == "CANDIDATE_REVIEW"
    assert candidate["evidence_status"] == "Research Evidence Available / Institutional Validation Pending"
    assert composite["is_combined"] is True


def test_paper_allocation_existing_sleeves_scale_down_without_fake_cash(tmp_path: Path) -> None:
    payload = build_paper_allocation_proposal(
        tmp_path,
        now=datetime(2026, 6, 29, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    active_targets = [row["suggested_weight"] for row in payload["rows"] if row["current_weight"] > 0]
    assert abs(sum(active_targets) - 0.98) <= payload["weight_sum_tolerance"]
    assert all(row["strategy_uid"] != "cash" for row in payload["rows"])
    assert payload["auto_apply_allowed"] is False
    assert payload["financial_state_mutated"] is False


def test_missing_ml_attribution_requires_review_but_does_not_freeze_proposal(tmp_path: Path) -> None:
    payload = build_paper_allocation_proposal(
        tmp_path,
        now=datetime(2026, 6, 29, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    assert payload["summary"]["review_required_count"] > 0
    assert any(row["delta"] != 0 for row in payload["rows"])
    assert payload["summary"]["increase_count"] > 0
    assert payload["summary"]["reduce_count"] > 0
    assert sum(row["suggested_weight"] for row in payload["rows"]) == payload["target_weight_sum"]


def test_paper_allocation_report_writes_review_only_artifact(tmp_path: Path) -> None:
    proposal = build_paper_allocation_proposal(
        tmp_path,
        now=datetime(2026, 6, 29, tzinfo=timezone.utc),
        strategy_intelligence_payload=_cards(),
    )

    report = write_paper_allocation_report(
        tmp_path,
        [
            {
                "strategy_uid": row["strategy_uid"],
                "display_name": row["display_name"],
                "current_weight": row["current_weight"],
                "suggested_weight": row["suggested_weight"],
                "target_weight": row["target_weight"],
                "action": row["suggested_action"],
                "reason": row["short_reason"],
                "score": row["score"],
            }
            for row in proposal["rows"]
        ],
        source_proposal_artifact="test-only/paper_allocation_proposal.json",
        draft_summary={"targetSum": proposal["target_weight_sum"]},
        now=datetime(2026, 6, 29, 12, tzinfo=timezone.utc),
    )

    assert report["source"] == "paper_allocation_workbench_report_v1"
    assert report["sums_to_100pct"] is True
    assert report["financial_state_mutated"] is False
    assert report["approved_plan_created"] is False
    assert report["paper_apply_created"] is False
    assert report["live_trading"] is False
    assert (tmp_path / report["artifact_path"]).exists()


def test_selected_batch_job_writes_stage_artifact_without_financial_mutation(tmp_path: Path, monkeypatch) -> None:
    from src.automation import strategy_factory_selected_batch_job as job_module

    def fake_run_factory(root: Path, selected_material_ids: list[str]) -> dict:
        run_id = "test-run-id"
        run_dir = root / "output" / "strategy_factory" / "runs" / run_id
        run_dir.mkdir(parents=True)
        return {
            "ok": True,
            "run": {
                "run_id": run_id,
                "batch_id": "test-batch-id",
                "selected_material_ids": selected_material_ids,
                "selected_materials": [
                    {"material_id": material_id, "material_hash": f"hash-{idx}"}
                    for idx, material_id in enumerate(selected_material_ids, start=1)
                ],
                "batch_manifest": {"source": "TEST_SELECTED_BATCH"},
                "run_manifest_path": str(run_dir / "run_manifest.json"),
                "batch_manifest_path": str(run_dir / "batch_manifest.json"),
                "generated_artifacts": {
                    "current_run_candidate": str(run_dir / "current_run_candidate.json"),
                    "current_run_report": str(run_dir / "current_run_report.md"),
                },
            },
            "candidate": {
                "strategy_id": "test-candidate-id",
                "name": "Test Candidate",
                "recommendation": "REVIEW_REQUIRED",
            },
            "factory": {
                "stage_statuses": [
                    {"stage": "MATERIALS_ANALYZED", "status": "COMPLETED", "reason": "test complete"},
                    {"stage": "RESEARCH_CARD_CREATED", "status": "COMPLETED", "reason": "test complete"},
                    {"stage": "TEST_SPEC_CREATED", "status": "COMPLETED", "reason": "test complete"},
                    {"stage": "EVIDENCE_REPORT_CREATED", "status": "BLOCKED", "reason": "test blocked"},
                    {"stage": "ML_DIAGNOSTICS_RUN", "status": "BLOCKED", "reason": "test blocked"},
                ]
            },
        }

    monkeypatch.setattr(job_module, "run_factory", fake_run_factory)
    monkeypatch.setattr(job_module, "base_state", lambda root: {"ok": True})

    material_ids = ["test-material-id-a", "test-material-id-b", "test-material-id-c"]
    result = run_selected_batch_job(tmp_path, material_ids=material_ids)

    assert result["ok"] is True
    assert result["job"]["selected_material_count"] == len(material_ids)
    assert result["job"]["selected_material_ids"] == material_ids
    assert result["job"]["selected_material_hashes"] == ["hash-1", "hash-2", "hash-3"]
    assert result["job"]["selection_source"] == "TEST_SELECTED_BATCH"
    assert result["job"]["financial_state_mutated"] is False
    assert result["job"]["safety"]["approved_plan_created"] is False
    assert result["job"]["safety"]["paper_apply_created"] is False
    assert (tmp_path / result["artifact_path"]).exists()
    assert {row["status"] for row in result["job"]["stages"]} <= {"BLOCKED", "COMPLETE", "NOT_WIRED", "FAILED"}
    assert all("name" in row and "output_count" in row for row in result["job"]["stages"])
    outputs = result["job"]["outputs"]
    for key in (
        "research_cards",
        "test_specs",
        "evidence_reports",
        "backtest_outputs",
        "ml_gate_outputs",
        "robustness_outputs",
        "candidate_registry_updates",
    ):
        assert outputs[key]
        assert all("artifact_type" in row for row in outputs[key])
        assert all("exists" in row for row in outputs[key])
        assert all("status" in row for row in outputs[key])
        assert all("labels" in row for row in outputs[key])
    assert outputs["research_cards"][0]["material_id"] == material_ids[0]
    assert outputs["ml_gate_outputs"][0]["exists"] is False
    assert "Missing ML Evidence" in outputs["ml_gate_outputs"][0]["labels"]
    assert outputs["robustness_outputs"][0]["exists"] is False
    assert "Missing Robustness Evidence" in outputs["robustness_outputs"][0]["labels"]
    assert outputs["candidate_registry_updates"][0]["candidate_id"] == "test-candidate-id"


def test_p0_generation_paths_do_not_mutate_canonical_paper_state(tmp_path: Path, monkeypatch) -> None:
    """Observed before/after byte-hash proof that P0 proposal/report/job generation
    never mutates canonical paper financial artifacts.

    This replaces self-reported ``financial_state_mutated: False`` flags (which only
    prove a dict literal) with an assertion on the actual bytes of the canonical
    approved-plan / applied-event / current-target files.
    """
    import hashlib
    import json as _json

    from src.automation import strategy_factory_selected_batch_job as job_module
    from src.automation.paper_allocation_proposal import (
        read_latest_paper_allocation_proposal,
        write_paper_allocation_proposal,
    )

    paper_dir = tmp_path / "data" / "paper_rebalance"
    paper_dir.mkdir(parents=True)
    canonical_seed = {
        "approved_rebalance_plans.json": {
            "plans": [{"plan_id": "seed-plan", "status": "APPROVED_WAITING_EFFECTIVE_DATE"}]
        },
        "applied_rebalance_events.json": {"events": []},
        "current_paper_target_weights.json": {"weights": {}},
    }
    before: dict[str, str] = {}
    for name, payload in canonical_seed.items():
        path = paper_dir / name
        path.write_text(_json.dumps(payload, indent=2), encoding="utf-8")
        before[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    now = datetime(2026, 6, 29, tzinfo=timezone.utc)

    missing = read_latest_paper_allocation_proposal(tmp_path)
    assert missing["ok"] is False
    assert not (tmp_path / "data" / "automation" / "allocation_proposals").exists()

    write_paper_allocation_proposal(tmp_path, now=now, strategy_intelligence_payload=_cards())
    proposal = build_paper_allocation_proposal(
        tmp_path, now=now, strategy_intelligence_payload=_cards()
    )
    write_paper_allocation_report(
        tmp_path,
        [
            {
                "strategy_uid": row["strategy_uid"],
                "current_weight": row["current_weight"],
                "target_weight": row["target_weight"],
                "action": row["suggested_action"],
            }
            for row in proposal["rows"]
        ],
        now=now,
    )

    def fake_run_factory(root: Path, selected_material_ids: list[str]) -> dict:
        run_dir = root / "output" / "strategy_factory" / "runs" / "hash-test-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "run": {"run_id": "hash-test-run", "selected_material_ids": selected_material_ids},
            "candidate": {"strategy_id": "hash-test-candidate", "recommendation": "REVIEW_REQUIRED"},
            "factory": {"stage_statuses": []},
        }

    monkeypatch.setattr(job_module, "run_factory", fake_run_factory)
    monkeypatch.setattr(job_module, "base_state", lambda root: {"ok": True})
    run_selected_batch_job(tmp_path, material_ids=["mat-a", "mat-b"])

    for name in canonical_seed:
        after = hashlib.sha256((paper_dir / name).read_bytes()).hexdigest()
        assert after == before[name], f"P0 generation mutated canonical artifact {name}"
