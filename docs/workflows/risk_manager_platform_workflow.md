# Multi-Strategy Risk Manager Platform Workflow

This workflow is the primary visual map for the project.

It is designed for a hedge fund / asset manager multi-strategy portfolio risk management workstation. It is not an ETF ranking workflow and it does not treat the risk manager as the owner of the alpha proposal.

## Reading Order

1. **Data & Controls** collects market, macro, news, position, and governance inputs.
2. **Strategy Research & Evidence** converts strategy definitions into cost-adjusted backtests, walk-forward evidence, and risk packets.
3. **Portfolio Proposal** is owned by Portfolio Management / Portfolio Construction.
4. **Independent Risk Review** challenges the proposal through limits, factor exposure, correlation, stress, cost, and evidence.
5. **Decision, Execution & Monitoring** records the human decision and compares expected outcomes with realized outcomes.

The dashboard artifact and audit trail connect every stage to the workstation.

## Responsibility Boundary

- Portfolio Manager / Portfolio Construction owns the investment thesis and proposed allocation.
- Independent Risk Manager reviews and challenges the proposal.
- Authorized Human Approver makes the final decision.
- Trading / Operations executes only after authorization.
- Risk and Operations monitor expectation versus realized outcomes.

## Decision Outcomes

- Approve
- Approve with Conditions
- Reject
- Escalate

No system recommendation can authorize real execution.

## Feedback Loops

- A rejected or conditional proposal returns to Portfolio Construction for modification.
- Monitoring failures return to risk limits, strategy research, and proposal assumptions.
- Data-quality failures block downstream conclusions.

## Visual Artifact

The rendered workflow is available at:

- `output/workflows/risk_manager_platform_workflow.html`
- `output/workflows/risk_manager_platform_workflow.png`

