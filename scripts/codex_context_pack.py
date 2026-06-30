"""Print compact repository context for Codex tasks.

The script avoids broad reads and excludes generated/local artifact paths by
default so future agents can start from a small, relevant context pack.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


DEFAULT_EXCLUDES = ("data/", "output/", "REVIEW_")


def run_git(args: list[str]) -> tuple[int, str]:
    process = subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return process.returncode, process.stdout.strip()


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_excluded(path: str) -> bool:
    normalized = normalize_path(path)
    return any(normalized == item.rstrip("/") or normalized.startswith(item) for item in DEFAULT_EXCLUDES)


def print_section(title: str, body: str) -> None:
    print(f"\n## {title}")
    print(body if body else "(none)")


def compact_status() -> str:
    code, output = run_git(["status", "--short"])
    if code != 0:
        return output

    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return "clean"

    tracked = 0
    untracked = 0
    relevant_lines: list[str] = []
    for line in lines:
        path = normalize_path(line[3:].strip() if len(line) > 3 else line.strip())
        if is_excluded(path):
            continue
        if line.startswith("??"):
            untracked += 1
        else:
            tracked += 1
        relevant_lines.append(line)

    summary = f"tracked={tracked} untracked={untracked}"
    if relevant_lines:
        return summary + "\n" + "\n".join(relevant_lines[:50])
    return summary


def changed_files() -> str:
    code, output = run_git(["diff", "--name-only", "origin/main...HEAD"])
    if code != 0:
        return output

    files = [normalize_path(line) for line in output.splitlines() if line.strip()]
    files = [path for path in files if not is_excluded(path)]
    return "\n".join(files)


def last_commits() -> str:
    code, output = run_git(["log", "--oneline", "-5"])
    return output if code == 0 else output


def iter_allowed_files(allowed_paths: list[str], max_files: int) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for raw_allowed in allowed_paths:
        allowed = Path(raw_allowed)
        if not allowed.exists():
            continue

        if allowed.is_file():
            candidates = [allowed]
        else:
            candidates = [path for path in allowed.rglob("*") if path.is_file()]

        for path in candidates:
            normalized = normalize_path(os.fspath(path))
            if normalized in seen or is_excluded(normalized):
                continue
            seen.add(normalized)
            results.append(normalized)
            if len(results) >= max_files:
                return results

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print a compact Codex context pack without reading generated artifacts."
    )
    parser.add_argument(
        "--allowed-path",
        action="append",
        default=[],
        help="Path to list compactly. May be passed more than once.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=80,
        help="Maximum relevant files to list under allowed paths.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    branch_code, branch = run_git(["branch", "--show-current"])
    print_section("Current Branch", branch if branch_code == 0 else branch)
    print_section("Changed Files vs origin/main", changed_files())
    print_section("Compact Git Status", compact_status())
    print_section("Last 5 Commits", last_commits())

    if args.allowed_path:
        files = iter_allowed_files(args.allowed_path, max(0, args.max_files))
        print_section("Relevant Files Under Allowed Paths", "\n".join(files))
    else:
        print_section("Relevant Files Under Allowed Paths", "pass --allowed-path to list scoped files")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
