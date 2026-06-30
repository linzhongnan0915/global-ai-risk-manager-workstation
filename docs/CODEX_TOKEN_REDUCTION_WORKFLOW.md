# Codex Token Reduction Workflow

This workflow keeps future Codex tasks narrow, cheap, and verifiable. It does not change product behavior, dashboard behavior, backend behavior, accounting logic, strategy definitions, Combined/N semantics, or operational records.

## Operating Rules

- Start with `git status --short`, `git diff --stat`, and the branch name before reading project files.
- Inspect changed files first. Treat unchanged files as out of scope unless the task requires a precise reference.
- Never read whole files unless necessary. Prefer outlines, symbol searches, and narrow line windows.
- Use targeted search (`rg`, file-specific grep, symbol names, endpoint names, or test names) instead of whole-repo scanning.
- Use file outlines before full reads: imports, function/class names, route declarations, test names, and compact section headers.
- Avoid reading `data/**`, `output/**`, `REVIEW_*`, screenshots, logs, caches, and local browser artifacts unless explicitly requested.
- Avoid repeated project background in responses. Link or name the relevant doc when needed.
- Summarize long command output before returning it. Keep failure headers, error lines, traceback starts, and final pass/fail counts.
- Return only a compact evidence pack: branch, SHA, files, diff stat, docs/scripts touched, validation, git status, and scoped confirmations.
- Stop after completing the requested objective. Do not broaden scope, opportunistically refactor, or add unrelated cleanup.
- One PR equals one objective. Split new objectives into later work.
- Do not paste huge JSON, generated artifacts, logs, or screenshots into text responses.

## Recommended Task Loop

1. Confirm branch and dirty state.
2. Identify allowed and forbidden paths from the task.
3. Inspect diffs and changed files.
4. Retrieve compact context only from relevant files.
5. Edit only the allowed files.
6. Run focused validation first.
7. Compress command evidence before returning it.
8. Report minimal evidence and stop.

## Context Pack Usage

Use `scripts/codex_context_pack.py` to avoid rereading the repo:

```powershell
python scripts/codex_context_pack.py --allowed-path dashboard --max-files 40
```

Use multiple `--allowed-path` values only when the task explicitly spans those areas.

## Command Output Compression

Pipe long command output through `scripts/compact_command_output.py` when preparing evidence:

```powershell
python -m pytest tests/test_operational_snapshot.py -q 2>&1 | python scripts/compact_command_output.py
git status --short 2>&1 | python scripts/compact_command_output.py
```

## Tool Evaluation

Do not install these tools in this release branch. Future use must remain local, opt-in, and outside production runtime dependencies.

| Tool | Evaluation | Safe Future Usage |
| --- | --- | --- |
| RTK | Likely useful later for command output compression. | Evaluate in local-only agent workflow for test/log summarization. |
| tokenix | Useful later for local repo symbol/index context. | Evaluate as a local index to reduce broad file reads. |
| jCodeMunch | Useful later for MCP symbol retrieval. | Evaluate for symbol-level retrieval when MCP access is approved. |
| Headroom | Maybe later; proxy layer, not now. | Consider only outside production code and without package changes. |
| OmniRoute | Not now; API gateway risk. | Avoid for this repo unless release scope explicitly changes. |
| ClaudeMem/memory tools | Maybe later, not production repo. | Keep memory stores outside repo or in ignored local cache paths. |

## Non-Goals

- No external model routing.
- No API gateways.
- No production runtime dependencies.
- No deployment.
- No dashboard or backend behavior changes.
