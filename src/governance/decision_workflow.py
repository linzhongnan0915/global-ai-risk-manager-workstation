"""Institutional proposal, independent review, approval, and monitoring workflow."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def build_decision_workflow(
    as_of_date: str,
    allocation: dict[str, Any],
    decision_review: dict[str, Any],
    risk_limits: dict[str, Any],
) -> dict[str, Any]:
    """Build a governance record without pretending an unmade human decision exists."""

    proposal_id = f"RMP-{as_of_date.replace('-', '')}-REBAL-001"
    blocking_gates = [
        gate for gate in decision_review.get("double_check_gates", []) if gate.get("status") == "fail"
    ]
    warning_gates = [
        gate for gate in decision_review.get("double_check_gates", []) if gate.get("status") == "warning"
    ]
    proposed_trades = allocation.get("rebalance_trade_list", [])
    review_due = (date.fromisoformat(as_of_date) + timedelta(days=1)).isoformat()
    monitoring_plan = decision_review.get("post_decision_monitoring_plan", {})

    return {
        "workflow_id": proposal_id,
        "workflow_status": _workflow_status(decision_review),
        "segregation_of_duties": {
            "proposal_owner_role": "Portfolio Manager / Portfolio Construction",
            "proposal_owner": "unassigned",
            "independent_risk_reviewer_role": "Independent Risk Manager",
            "independent_risk_reviewer": "unassigned",
            "decision_authority_role": "Authorized Human Approver",
            "decision_authority": "unassigned",
            "execution_owner_role": "Trading / Operations",
            "execution_owner": "unassigned",
            "risk_manager_does_not_own_alpha_proposal": True,
        },
        "stage_1_proposal": {
            "proposal_id": proposal_id,
            "status": "submitted_for_independent_risk_review",
            "proposal_type": "multi_strategy_rebalance",
            "submitted_at": f"{as_of_date}T16:30:00-04:00",
            "proposal_owner": "unassigned",
            "objective": "Improve portfolio risk-adjusted profile within configured limits.",
            "investment_thesis": "Score-tilted portfolio construction proposal. Thesis requires PM documentation before approval.",
            "trigger": _proposal_trigger(risk_limits),
            "current_weights": allocation.get("current_weights", {}),
            "proposed_weights": allocation.get("proposed_weights", {}),
            "trade_count": len(proposed_trades),
            "estimated_transaction_cost": allocation.get("estimated_transaction_cost", 0.0),
            "required_pm_inputs": [
                "Document expected alpha source and investment thesis.",
                "Explain why proposed increases are appropriate under current regime.",
                "Confirm liquidity, capacity, and execution assumptions.",
                "Identify proposal expiry and acceptable implementation window.",
            ],
        },
        "stage_2_independent_risk_review": {
            "status": "completed_system_review_pending_human_risk_signoff",
            "reviewer": "unassigned",
            "review_due_date": review_due,
            "system_conclusion": decision_review.get("final_decision"),
            "system_approval_status": decision_review.get("approval_status"),
            "blocking_objections": blocking_gates,
            "warnings_and_conditions": warning_gates,
            "required_modifications": decision_review.get("required_modifications", []),
            "expected_impact": decision_review.get("expected_impact", {}),
            "limitations": decision_review.get("decision_limitations", []),
            "risk_questions_for_human_reviewer": [
                "Does the proposal solve the original risk problem?",
                "Does it introduce a new concentration, liquidity, or tail-risk problem?",
                "Are the expected benefits material relative to uncertainty and cost?",
                "Should any warning-status strategy receive additional capital?",
                "Are stress and correlation assumptions credible under current market conditions?",
            ],
        },
        "stage_3_decision_authority": {
            "status": "pending_human_decision",
            "authority": "unassigned",
            "allowed_outcomes": ["Approve", "Approve with Conditions", "Reject", "Escalate"],
            "system_recommended_outcome": _authority_recommendation(decision_review),
            "decision_outcome": None,
            "decision_timestamp": None,
            "conditions": [],
            "override_requested": False,
            "override_reason": None,
            "override_approver": None,
            "decision_expiry_date": review_due,
            "execution_authorized": False,
        },
        "stage_4_execution_and_monitoring": {
            "execution_status": "not_authorized_not_executed",
            "execution_timestamp": None,
            "executed_weights": None,
            "realized_transaction_cost": None,
            "expectation_snapshot": monitoring_plan.get("decision_expectation", {}),
            "monitoring_checkpoints": _pending_checkpoints(monitoring_plan.get("checkpoints", [])),
            "invalidation_criteria": monitoring_plan.get("invalidation_criteria", []),
            "realized_outcome_status": "awaiting_authorized_execution",
            "expectation_vs_realized": None,
        },
        "audit_trail": [
            {
                "timestamp": f"{as_of_date}T16:30:00-04:00",
                "actor": "system",
                "event": "proposal_generated",
                "note": "Portfolio construction proposal generated for independent risk review.",
            },
            {
                "timestamp": f"{as_of_date}T16:31:00-04:00",
                "actor": "system_risk_review",
                "event": "independent_system_review_completed",
                "note": decision_review.get("final_decision"),
            },
        ],
    }


def _workflow_status(decision_review: dict[str, Any]) -> str:
    status = decision_review.get("approval_status")
    if status == "blocked_pending_modification":
        return "risk_review_blocked_pending_pm_modification"
    if status == "pending_modification_and_human_review":
        return "risk_review_conditions_pending"
    return "pending_human_decision"


def _proposal_trigger(risk_limits: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "limit_id": check.get("limit_id"),
            "scope": check.get("scope"),
            "metric": check.get("metric"),
            "status": check.get("status"),
        }
        for check in risk_limits.get("checks", [])
        if check.get("status") in {"warning", "breach"}
    ]


def _authority_recommendation(decision_review: dict[str, Any]) -> str:
    status = decision_review.get("approval_status")
    if status == "blocked_pending_modification":
        return "Reject"
    if status == "pending_modification_and_human_review":
        return "Approve with Conditions"
    return "Escalate for Human Approval"


def _pending_checkpoints(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **checkpoint,
            "status": "pending_execution",
            "observed_values": None,
            "reviewer_note": None,
            "outcome": None,
        }
        for checkpoint in checkpoints
    ]
