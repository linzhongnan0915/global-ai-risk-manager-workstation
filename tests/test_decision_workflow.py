from src.governance.decision_workflow import build_decision_workflow


def test_workflow_separates_proposal_risk_review_and_authority():
    workflow = build_decision_workflow(
        "2026-06-05",
        {
            "current_weights": {"A": 1.0},
            "proposed_weights": {"A": 1.0},
            "rebalance_trade_list": [],
            "estimated_transaction_cost": 0.0,
        },
        {
            "final_decision": "Approve For Human Review",
            "approval_status": "pending_human_approval",
            "double_check_gates": [],
            "required_modifications": [],
            "expected_impact": {},
            "decision_limitations": [],
            "post_decision_monitoring_plan": {"decision_expectation": {}, "checkpoints": [], "invalidation_criteria": []},
        },
        {"checks": []},
    )

    duties = workflow["segregation_of_duties"]
    assert duties["risk_manager_does_not_own_alpha_proposal"] is True
    assert workflow["stage_3_decision_authority"]["decision_outcome"] is None
    assert workflow["stage_3_decision_authority"]["execution_authorized"] is False
    assert workflow["stage_4_execution_and_monitoring"]["execution_status"] == "not_authorized_not_executed"


def test_blocked_review_recommends_reject_without_fake_human_decision():
    workflow = build_decision_workflow(
        "2026-06-05",
        {"rebalance_trade_list": [], "estimated_transaction_cost": 50.0},
        {
            "final_decision": "Reject / Redesign Proposed Rebalance",
            "approval_status": "blocked_pending_modification",
            "double_check_gates": [{"gate": "x", "status": "fail"}],
            "required_modifications": [{"scope": "A"}],
            "expected_impact": {},
            "decision_limitations": [],
            "post_decision_monitoring_plan": {"decision_expectation": {}, "checkpoints": [], "invalidation_criteria": []},
        },
        {"checks": []},
    )

    authority = workflow["stage_3_decision_authority"]
    assert workflow["workflow_status"] == "risk_review_blocked_pending_pm_modification"
    assert authority["system_recommended_outcome"] == "Reject"
    assert authority["decision_outcome"] is None
