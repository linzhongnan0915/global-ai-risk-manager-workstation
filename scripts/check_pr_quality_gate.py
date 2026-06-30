"""Local PR quality gate for the GlobalAI Research Factory release repo.

The gate scans the current diff, not the historical repository. It is intended
to catch product-truth regressions before review: hardcoded portfolio truth,
fake evidence claims, generated artifact staging, and paper/live safety wording.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Iterable


SELF_PATH = "scripts/check_pr_quality_gate.py"

GENERATED_STAGED_PATTERNS = (
    re.compile(r"^REVIEW_"),
    re.compile(r"^.*\.zip$", re.IGNORECASE),
    re.compile(r"^data/automation/"),
    re.compile(r"^data/paper_rebalance/applied_rebalance_events\.json$"),
    re.compile(r"^data/paper_rebalance/current_paper_target_weights\.json$"),
    re.compile(r"^output/"),
)

STRATEGY_IDENTITY_RE = re.compile(
    r"\b(Copper|Low Vol|C3A[A-Z0-9_]*|WQ(?:_ALPHA)?[A-Z0-9_]*|COMBINED_PORTFOLIO)\b",
    re.IGNORECASE,
)
FORBIDDEN_TOKEN_RE = re.compile(
    r"\b(EXPECTED_[A-Z0-9_]*|INITIAL_[A-Z0-9_]*|TOP_LEVEL_ACTIVE|ORDINARY_ACTIVE|"
    r"ACTIVE_SLEEVES|ACTIVE_STRATEGY_COUNT|ORDINARY_ACTIVE_COUNT|TOP_LEVEL_ACTIVE_COUNT|"
    r"SLEEVE_DENOMINATOR|STARTING_CAPITAL_DENOMINATOR)\b"
)
BRANCH_CONTEXT_RE = re.compile(r"\b(if|elif|else\s+if|switch|case|when|match)\b|==|===|!=|!==|\.includes\(| in ")
COUNT_ASSIGNMENT_RE = re.compile(
    r"\b(active_count|strategy_count|sleeve_count|denominator|sleeve_weight|starting_capital|"
    r"allocation_weight|top_level_count|ordinary_count)\b[^\n=:{]{0,40}[:=]\s*[0-9]+(?:\.[0-9]+)?\b",
    re.IGNORECASE,
)
DERIVED_COUNT_RE = re.compile(r"\b(len|sum|count|filter|map|reduce|rows|registry|snapshot|artifact|metadata|config)\b", re.IGNORECASE)
POLICY_EXCEPTION_RE = re.compile(r"\b(policy|starter|constant|generic)\b", re.IGNORECASE)

FAKE_CLAIM_RE = re.compile(
    r"\b(ML validated|SHAP available|permutation importance available|VaR available|CVaR available|"
    r"regime proven|attribution complete|causal proof|alpha proven|guaranteed alpha|"
    r"robustly validated|institutional approved|production alpha)\b",
    re.IGNORECASE,
)
HONEST_QUALIFIER_RE = re.compile(
    r"\b(Missing|Pending|Prototype|Not Available|Not proven|Research only|"
    r"Institutional Validation Pending|Public Fallback|Not PIT|Not survivor-bias-free)\b",
    re.IGNORECASE,
)

LIVE_SAFETY_RE = re.compile(
    r"\b(live trading approved|brokerage execution enabled|live fill|real fill|broker order|"
    r"order sent|executed live|official NAV mutation|GET mutates ledger|auto apply without confirmation)\b",
    re.IGNORECASE,
)
SAFETY_NEGATION_RE = re.compile(r"\b(disabled|false|no|not live|paper only|paper-only|none|blocked)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AddedLine:
    file: str
    line: int | None
    text: str


@dataclass(frozen=True)
class Violation:
    check_name: str
    file: str
    line: int | None
    severity: str
    message: str


def _run_git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip()


def is_test_or_fixture(path: str, *, allow_tests_fixtures: bool = True) -> bool:
    path = _norm(path)
    if path.startswith("tests/"):
        if allow_tests_fixtures:
            return True
        return not path.startswith("tests/fixtures/")
    return False


def is_gate_tooling(path: str) -> bool:
    path = _norm(path)
    return path == SELF_PATH or path == "tests/test_pr_quality_gate.py"


def is_production_scan_file(path: str) -> bool:
    path = _norm(path)
    if is_test_or_fixture(path) or is_gate_tooling(path):
        return False
    return path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".json", ".yaml", ".yml"))


def parse_added_lines(diff_text: str) -> list[AddedLine]:
    lines: list[AddedLine] = []
    current_file = ""
    new_line: int | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = _norm(raw[6:])
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            new_line = int(match.group(1)) if match else None
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lines.append(AddedLine(current_file, new_line, raw[1:]))
            if new_line is not None:
                new_line += 1
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            continue
        if new_line is not None:
            new_line += 1
    return lines


def changed_files_from_diff_name_status(text: str) -> list[str]:
    files: list[str] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        if parts[0].startswith("R") and len(parts) >= 3:
            files.append(_norm(parts[2]))
        elif len(parts) >= 2:
            files.append(_norm(parts[1]))
    return files


def staged_generated_violations(staged_files: Iterable[str], *, allow_tests_fixtures: bool) -> list[Violation]:
    violations: list[Violation] = []
    for raw in staged_files:
        path = _norm(raw)
        if not path:
            continue
        if allow_tests_fixtures and path.startswith("tests/fixtures/"):
            continue
        if any(pattern.search(path) for pattern in GENERATED_STAGED_PATTERNS):
            violations.append(
                Violation(
                    "generated_artifact_staging",
                    path,
                    None,
                    "FAIL",
                    "Generated/proof/runtime artifact is staged; do not stage generated artifacts.",
                )
            )
    return violations


def dynamic_no_hardcode_violations(lines: Iterable[AddedLine]) -> list[Violation]:
    violations: list[Violation] = []
    for line in lines:
        if not is_production_scan_file(line.file):
            continue
        text = line.text
        if STRATEGY_IDENTITY_RE.search(text) and BRANCH_CONTEXT_RE.search(text):
            violations.append(
                Violation("dynamic_no_hardcode", line.file, line.line, "FAIL", "Strategy name/id appears in production branch logic.")
            )
        if FORBIDDEN_TOKEN_RE.search(text):
            violations.append(
                Violation("dynamic_no_hardcode", line.file, line.line, "FAIL", "Forbidden hardcoded portfolio/count token appears in production code.")
            )
        if COUNT_ASSIGNMENT_RE.search(text) and not DERIVED_COUNT_RE.search(text):
            if "sleeve_weight" in text.lower() or "allocation_weight" in text.lower():
                if POLICY_EXCEPTION_RE.search(text):
                    continue
            violations.append(
                Violation(
                    "dynamic_no_hardcode",
                    line.file,
                    line.line,
                    "FAIL",
                    "Numeric literal assigned near count/denominator/weight identifier; derive from artifacts or metadata.",
                )
            )
    return violations


def fake_evidence_violations(lines: Iterable[AddedLine]) -> list[Violation]:
    violations: list[Violation] = []
    for line in lines:
        if not is_production_scan_file(line.file):
            continue
        if FAKE_CLAIM_RE.search(line.text) and not HONEST_QUALIFIER_RE.search(line.text):
            violations.append(
                Violation(
                    "fake_evidence_claim",
                    line.file,
                    line.line,
                    "FAIL",
                    "Unsupported ML/risk/regime/attribution authority language without missing/pending/prototype qualifier.",
                )
            )
    return violations


def live_safety_violations(lines: Iterable[AddedLine]) -> list[Violation]:
    violations: list[Violation] = []
    for line in lines:
        if not is_production_scan_file(line.file):
            continue
        if LIVE_SAFETY_RE.search(line.text) and not SAFETY_NEGATION_RE.search(line.text):
            violations.append(
                Violation(
                    "paper_live_safety",
                    line.file,
                    line.line,
                    "FAIL",
                    "Line implies live trading/fills/orders/NAV mutation/auto-apply without clear disabled or paper-only qualifier.",
                )
            )
    return violations


def category_summary(files: Iterable[str]) -> dict[str, bool]:
    normalized = [_norm(path) for path in files]
    return {
        "dashboard changed": any(path.startswith("dashboard/") for path in normalized),
        "src changed": any(path.startswith("src/") for path in normalized),
        "tests changed": any(path.startswith("tests/") for path in normalized),
        "scripts changed": any(path.startswith("scripts/") for path in normalized),
        "data changed": any(path.startswith("data/") for path in normalized),
        "output changed": any(path.startswith("output/") for path in normalized),
    }


def evaluate(diff_text: str, changed_files: list[str], staged_files: list[str], *, allow_tests_fixtures: bool = True) -> tuple[list[Violation], dict[str, bool]]:
    added_lines = parse_added_lines(diff_text)
    violations: list[Violation] = []
    violations.extend(staged_generated_violations(staged_files, allow_tests_fixtures=allow_tests_fixtures))
    violations.extend(dynamic_no_hardcode_violations(added_lines))
    violations.extend(fake_evidence_violations(added_lines))
    violations.extend(live_safety_violations(added_lines))
    return violations, category_summary(changed_files)


def git_inputs(base: str, *, staged_only: bool) -> tuple[str, list[str], list[str]]:
    if staged_only:
        diff_text = _run_git(["diff", "--cached", "--unified=0"])
        name_status = _run_git(["diff", "--cached", "--name-status"])
    else:
        diff_text = _run_git(["diff", "--unified=0", f"{base}...HEAD"])
        name_status = _run_git(["diff", "--name-status", f"{base}...HEAD"])
    changed_files = changed_files_from_diff_name_status(name_status)
    staged_files = [_norm(path) for path in _run_git(["diff", "--cached", "--name-only"]).splitlines() if path.strip()]
    return diff_text, changed_files, staged_files


def print_report(violations: list[Violation], categories: dict[str, bool], changed_files: list[str], staged_files: list[str], *, json_output: bool) -> None:
    fail = any(v.severity == "FAIL" for v in violations)
    if json_output:
        print(
            json.dumps(
                {
                    "status": "FAIL" if fail else "PASS",
                    "changed_files": changed_files,
                    "category_summary": categories,
                    "staged_generated_artifact_status": "FAIL" if any(v.check_name == "generated_artifact_staging" for v in violations) else "PASS",
                    "staged_files": staged_files,
                    "violations": [asdict(v) for v in violations],
                },
                indent=2,
            )
        )
        return
    print("FAIL" if fail else "PASS")
    print()
    print("Changed files:")
    for path in changed_files:
        print(f"  - {path}")
    if not changed_files:
        print("  (none)")
    print()
    print("Changed file category summary:")
    for label, value in categories.items():
        print(f"  {label}: {'yes' if value else 'no'}")
    generated_status = "FAIL" if any(v.check_name == "generated_artifact_staging" for v in violations) else "PASS"
    print(f"staged generated artifact status: {generated_status}")
    print()
    print("Violations:")
    print("check_name | file | line | severity | message")
    if not violations:
        print("(none)")
    for v in violations:
        print(f"{v.check_name} | {v.file} | {v.line or ''} | {v.severity} | {v.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GlobalAI Research Factory PR quality gate")
    parser.add_argument("--base", default="origin/main", help="base ref for diff scan")
    parser.add_argument("--staged-only", action="store_true", help="scan only staged diff content")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument("--allow-tests-fixtures", action="store_true", default=True, help="allow generated-looking files under tests/fixtures")
    args = parser.parse_args(argv)

    diff_text, changed_files, staged_files = git_inputs(args.base, staged_only=args.staged_only)
    violations, categories = evaluate(
        diff_text,
        changed_files,
        staged_files,
        allow_tests_fixtures=args.allow_tests_fixtures,
    )
    print_report(violations, categories, changed_files, staged_files, json_output=args.json)
    return 1 if any(v.severity == "FAIL" for v in violations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
