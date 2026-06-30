"""Compress command, pytest, and git status output for compact Codex evidence."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


KEY_LINE_RE = re.compile(
    r"(FAIL|FAILED|ERROR|Error|Traceback|AssertionError|PASS|PASSED|passed|failed|errors?|warnings?)"
)
PYTEST_SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>passed|failed|error|errors|skipped|xfailed|xpassed|warnings?)"
)


def read_input(file_path: str | None) -> str:
    if file_path:
        return Path(file_path).read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def truncate_repeated_lines(lines: list[str], repeat_limit: int = 3) -> list[str]:
    output: list[str] = []
    repeats: Counter[str] = Counter()
    suppressed = 0

    for line in lines:
        normalized = line.strip()
        repeats[normalized] += 1
        if normalized and repeats[normalized] > repeat_limit:
            suppressed += 1
            continue
        output.append(line)

    if suppressed:
        output.append(f"... suppressed {suppressed} repeated lines ...")
    return output


def summarize_pytest(text: str) -> list[str]:
    matches = PYTEST_SUMMARY_RE.findall(text)
    if not matches:
        return []

    counts: Counter[str] = Counter()
    for count, kind in matches:
        normalized = "error" if kind.startswith("error") else kind.rstrip("s")
        counts[normalized] += int(count)

    parts = [f"{kind}={count}" for kind, count in sorted(counts.items())]
    return ["PYTEST SUMMARY: " + " ".join(parts)]


def summarize_git_status(lines: list[str]) -> list[str]:
    status_lines = [line for line in lines if re.match(r"^(..|\?\?)\s+", line)]
    if not status_lines:
        return []

    tracked = 0
    untracked = 0
    staged_or_modified = 0

    for line in status_lines:
        if line.startswith("??"):
            untracked += 1
        else:
            tracked += 1
            if line[:2].strip():
                staged_or_modified += 1

    return [
        f"GIT STATUS SUMMARY: tracked={tracked} untracked={untracked} staged_or_modified={staged_or_modified}"
    ]


def extract_key_lines(lines: list[str], max_lines: int) -> list[str]:
    selected: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        if KEY_LINE_RE.search(stripped) or stripped.startswith(("E   ", "> ", "FAILED ")):
            selected.append(stripped)
        if len(selected) >= max_lines:
            selected.append(f"... truncated key lines at {max_lines} ...")
            break
    return selected


def compact_output(text: str, max_lines: int) -> str:
    raw_lines = text.splitlines()
    lines = truncate_repeated_lines(raw_lines)

    sections: list[str] = []
    sections.extend(summarize_pytest(text))
    sections.extend(summarize_git_status(raw_lines))

    key_lines = extract_key_lines(lines, max_lines)
    if key_lines:
        sections.append("KEY LINES:")
        sections.extend(key_lines)
    else:
        trimmed = [line.rstrip() for line in lines if line.strip()]
        if len(trimmed) > max_lines:
            trimmed = trimmed[:max_lines] + [f"... truncated output at {max_lines} lines ..."]
        sections.extend(trimmed)

    return "\n".join(sections).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compress command/test/git output into compact Codex evidence."
    )
    parser.add_argument("--file", help="Read command output from a file instead of stdin.")
    parser.add_argument(
        "--max-lines",
        type=int,
        default=80,
        help="Maximum key or fallback lines to print.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    text = read_input(args.file)
    print(compact_output(text, max(1, args.max_lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
