# Next Actions

## Remediation v1 Complete (2026-06-08)

Independent GPT review of branch `milestone/platform-remediation-v1`. See [PLATFORM_REMEDIATION_V1_HANDOFF.md](./PLATFORM_REMEDIATION_V1_HANDOFF.md).

## Highest Priority (Production Data)

1. Replace ETF-proxy strategy returns with boss API or live strategy return feeds.
2. Connect actual positions, fills, realized transaction costs, and reconciliation checks.
3. Add release-timed macro data and a validated portfolio-level regime model.
4. Connect a real news/event feed with source lineage and timestamp controls.
5. Calibrate provisional risk limits with PM and independent risk approval.

## Risk Logic And Governance

1. Persist human decisions to server-side audit storage (today: browser `localStorage` plus workflow artifact trail).
2. Recompute proposed correlation impact when weights change (current prototype holds return correlations fixed).
3. Add authorized execution handoff interface (still must remain separate from approval).
4. Monitor expected versus realized results after an authorized rebalance.

## Model And Research

1. Validate strategy definitions against investable implementation constraints.
2. Add survivorship-free and point-in-time datasets where required.
3. Add parameter-stability and multiple-testing controls.
4. Expand scenario tests and historical crisis replay.

## Product

1. Add named users and role-based approval controls.
2. Add exportable daily risk memo PDF with evidence packet attachments.
3. Add data-refresh scheduler and stale-data alerts.
4. Add saved risk-manager views and persistent strategy notes.

## Completed In Latest Handoff Pass

- Documentation and contract audit reconciled with implementation.
- Removed stale dashboard placeholder rendering paths.
- Added tested Python rebalance simulation and artifact embedding.
- Added workstation server with `/api/simulate`.
- Added browser verification script and nine-tab screenshots under `output/browser_verification/`.
- Generated `docs/REQUIREMENTS_TRACEABILITY.md`.
