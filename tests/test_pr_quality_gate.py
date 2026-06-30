from __future__ import annotations

from scripts import check_pr_quality_gate as gate


def _diff(path: str, *added_lines: str) -> str:
    body = "\n".join(f"+{line}" for line in added_lines)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(added_lines)} @@\n{body}\n"


def _evaluate(diff_text: str, *, changed: list[str] | None = None, staged: list[str] | None = None):
    return gate.evaluate(diff_text, changed or ["src/example.py"], staged or [])


def _failures(violations):
    return [violation for violation in violations if violation.severity == "FAIL"]


def test_clean_diff_passes():
    violations, categories = _evaluate("")

    assert violations == []
    assert categories["src changed"] is True


def test_hardcoded_strategy_name_as_production_branch_fails():
    violations, _ = _evaluate(_diff("src/example.py", 'if strategy_uid == "Copper":'))

    assert any(v.check_name == "dynamic_no_hardcode" for v in _failures(violations))


def test_hardcoded_count_assignment_fails_even_when_number_is_50():
    violations, _ = _evaluate(_diff("src/example.py", "active_count = 50"))

    assert any("Numeric literal assigned" in v.message for v in _failures(violations))


def test_dynamic_len_artifact_derived_count_passes():
    violations, _ = _evaluate(_diff("src/example.py", "active_count = len(snapshot_rows)"))

    assert _failures(violations) == []


def test_fake_shap_var_regime_attribution_claim_fails():
    violations, _ = _evaluate(
        _diff(
            "src/example.py",
            'status_text = "SHAP available and VaR available; regime proven; attribution complete"',
        )
    )

    assert any(v.check_name == "fake_evidence_claim" for v in _failures(violations))


def test_missing_pending_prototype_wording_passes():
    violations, _ = _evaluate(
        _diff(
            "src/example.py",
            'status_text = "SHAP available: Missing / Prototype / Institutional Validation Pending"',
        )
    )

    assert _failures(violations) == []


def test_staged_data_automation_artifact_fails():
    violations, _ = _evaluate("", staged=["data/automation/daily_cycle/2026-06-30.json"])

    assert any(v.check_name == "generated_artifact_staging" for v in _failures(violations))


def test_tests_fixtures_path_can_be_allowed():
    violations, _ = gate.evaluate(
        "",
        ["tests/fixtures/data/automation/example.json"],
        ["tests/fixtures/data/automation/example.json"],
        allow_tests_fixtures=True,
    )

    assert _failures(violations) == []


def test_live_trading_implication_fails():
    violations, _ = _evaluate(_diff("src/example.py", 'message = "brokerage execution enabled; order sent"'))

    assert any(v.check_name == "paper_live_safety" for v in _failures(violations))


def test_paper_only_disabled_language_passes():
    violations, _ = _evaluate(
        _diff("src/example.py", 'message = "brokerage execution disabled; no live fill; paper only"')
    )

    assert _failures(violations) == []


def test_report_prints_fail_table(capsys):
    violations, categories = _evaluate(_diff("src/example.py", "strategy_count = 50"))

    gate.print_report(violations, categories, ["src/example.py"], [], json_output=False)
    output = capsys.readouterr().out

    assert output.startswith("FAIL")
    assert "check_name | file | line | severity | message" in output
    assert "dynamic_no_hardcode | src/example.py | 1 | FAIL" in output
