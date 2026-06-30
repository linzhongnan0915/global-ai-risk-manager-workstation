# Codex Context Retrieval Rules

Use the smallest context that can answer the task. Prefer exact files, exact symbols, and focused tests over broad repository reads.

## Default Retrieval Order

1. Read task constraints and allowed paths.
2. Inspect `git status --short`, `git diff --stat`, and changed files.
3. Search exact symbols, endpoints, test names, or UI selectors.
4. Read narrow line ranges around matches.
5. Expand only when evidence shows the current context is insufficient.

## UI Tasks

For dashboard UI work, read only:

- `dashboard/index.html`
- `dashboard/foundation-app.js`
- `dashboard/foundation.css`

Read other dashboard files only when the user explicitly allows it or the focused search proves those files own the requested UI.

Screenshots are required for UI evidence, but do not paste full screenshots into text. Reference generated screenshot files or provide a compact visual summary.

## Backend Endpoint Tasks

For backend endpoint work, read only:

- the endpoint file
- the exact module called by the endpoint
- the exact tests covering the endpoint or module

Use endpoint maps, route search, and symbol search before opening files. Do not inspect unrelated services, strategy definitions, accounting code, or data artifacts.

Endpoint proof is required for backend changes: include the focused test or command and the compact result.

## Test Tasks

- Run focused tests first.
- Do not run the full suite unless requested or required by the release gate.
- Search test names and fixtures before opening whole test files.
- Return compact pass/fail counts and only relevant failure headers.

## Audit Tasks

Use this order:

1. `git diff --stat`
2. changed files
3. symbol search
4. endpoint map or route declarations
5. focused file windows

Do not perform whole-repo scans unless explicitly requested. If a scan is required, exclude generated and local artifact paths.

## Exclusions

Do not scan or read these paths unless explicitly requested:

- `data/**`
- `output/**`
- `REVIEW_*`
- screenshots
- logs
- caches
- `.env` or secrets
- local browser artifacts

Do not paste huge JSON, full artifacts, full screenshots, full logs, or large command outputs into responses.

## Response Context Budget

Keep evidence packs compact:

- changed files only
- focused validation only
- exact failures only
- short confirmations for forbidden paths
- no repeated project background
