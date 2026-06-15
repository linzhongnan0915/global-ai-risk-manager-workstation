"""Before/after rebalance gate evaluation for proposal safety."""

from __future__ import annotations

from typing import Any


def _index_checks(checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for check in checks:
        key = str(check.get("limit_id") or check.get("metric") or check.get("check_id"))
        indexed[key] = check
    return indexed


def evaluate_proposal_gates(
    checks_before: list[dict[str, Any]],
    checks_after: list[dict[str, Any]],
    *,
    turnover: float,
    tolerance: float = 1e-9,
) -> list[dict[str, Any]]:
    """Compare limit checks before and after a proposed rebalance.

    Rules:
    - Block new hard breaches.
    - Require exception review when a hard breach worsens materially.
    - Do not mark improvement when values are unchanged within tolerance.
    - Skip change warnings when turnover is zero.
    """

    if turnover <= tolerance:
        return [
            {
                "status": "ok",
                "metric": "proposal_change",
                "gate": "no_allocation_change",
                "text": "No weight change; proposal gates not re-evaluated.",
            }
        ]

    before = _index_checks(checks_before)
    after = _index_checks(checks_after)
    gates: list[dict[str, Any]] = []

    for key, post in after.items():
        pre = before.get(key)
        pre_status = pre.get("status") if pre else "ok"
        post_status = post.get("status")
        pre_value = float(pre.get("current_value", 0.0)) if pre and pre.get("current_value") is not None else None
        post_value = float(post.get("current_value", 0.0)) if post.get("current_value") is not None else None

        if post_status == "breach" and pre_status != "breach":
            gates.append(
                {
                    "status": "breach",
                    "metric": post.get("metric", key),
                    "gate": "new_hard_breach",
                    "check_id": key,
                    "text": f"Proposal creates a new hard breach on {post.get('metric', key)}.",
                    "required_action": "Modify proposal or document formal exception review.",
                }
            )
            continue

        if post_status == "breach" and pre_status == "breach" and pre_value is not None and post_value is not None:
            if abs(post_value) > abs(pre_value) + tolerance:
                gates.append(
                    {
                        "status": "warning",
                        "metric": post.get("metric", key),
                        "gate": "worsened_hard_breach",
                        "check_id": key,
                        "text": (
                            f"Existing hard breach on {post.get('metric', key)} worsens "
                            f"({pre_value:.4f} -> {post_value:.4f})."
                        ),
                        "required_action": "Formal exception review required before approval.",
                    }
                )
            elif abs(post_value - pre_value) <= tolerance:
                gates.append(
                    {
                        "status": "ok",
                        "metric": post.get("metric", key),
                        "gate": "unchanged_breach",
                        "check_id": key,
                        "text": f"Breach unchanged on {post.get('metric', key)}; not treated as improvement.",
                    }
                )

        if pre_status in {"breach", "warning", "watch"} and post_status == "ok" and pre_value is not None and post_value is not None:
            if abs(post_value - pre_value) <= tolerance:
                continue
            gates.append(
                {
                    "status": "ok",
                    "metric": post.get("metric", key),
                    "gate": "resolved_check",
                    "check_id": key,
                    "text": f"Check {post.get('metric', key)} improved under proposal.",
                }
            )

    return gates
