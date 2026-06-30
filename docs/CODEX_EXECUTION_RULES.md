# Codex Execution Rules

These rules govern future Codex execution in this repository. They are intended to reduce token use while preserving release safety.

## Branch And Scope

- Work on a feature branch only.
- Never work directly on `main`.
- One PR must have one objective.
- Stop after completing the requested objective.
- Do not broaden scope or perform unrelated cleanup.
- Do not deploy unless explicitly approved.

## Allowed And Forbidden Files

Every task must state allowed and forbidden files before edits begin. If it does not, infer the narrowest safe set and confirm it in the response.

For this release setup, allowed files are:

- `docs/CODEX_EXECUTION_RULES.md`
- `docs/CODEX_TOKEN_REDUCTION_WORKFLOW.md`
- `docs/CODEX_CONTEXT_RETRIEVAL_RULES.md`
- `scripts/codex_context_pack.py`
- `scripts/compact_command_output.py`
- `.gitignore` only for local Codex/cache ignores

Forbidden files include:

- `src/**`
- `dashboard/**`
- `scripts/run_workstation_server.py`
- `package.json`
- `package-lock.json`
- `requirements*`
- `data/**`
- `output/**`
- Render config
- `.env` or secrets

## Evidence Rules

- Use a compact return format.
- No self-reported `PASS` without proof.
- Include command, result, and relevant summary for validation.
- Screenshots are required for UI changes.
- Endpoint proof is required for backend changes.
- Do not paste full screenshots, full logs, huge JSON, or generated artifacts into text.
- No generated artifacts staged.

## Safety Rules

- Do not change strategy definitions.
- Do not change accounting logic.
- Do not change Combined/N semantics.
- Do not change WQ_ALPHA_018 admission status.
- Do not fabricate execution evidence, trades, holdings, NAV, P&L, or research metrics.
- Keep Historical Research separate from Operational records.
- Keep brokerage execution disabled unless a future explicit task changes release scope.
- No fake data.
- No hardcoded operational results.
- No live trading.

## Compact Return Format

Use this format when closing a development task:

```text
BRANCH:
SHA:
FILES:
DIFF STAT:
DOCS:
SCRIPT USAGE:
VALIDATION:
GIT STATUS:
CONFIRM no src/** changed:
CONFIRM no dashboard/** changed:
CONFIRM no data/** or output/** staged:
READY FOR GPT REVIEW: YES/NO
```
