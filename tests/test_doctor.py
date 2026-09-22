"""doctor.py reports adapters, reviewers and fixture health for a profile without the claude CLI."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"


def run_doctor(tmp_path, answers, *extra, key=None):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(answers), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    env.pop("TYPESAFE_API_KEY", None)
    if key:
        env["TYPESAFE_API_KEY"] = key
    run = subprocess.run([sys.executable, str(DOCTOR), "--profile", str(profile), *extra],
                         capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp_path)
    return run.returncode, run.stdout + run.stderr


def test_given_defaults_then_doctor_is_ok(tmp_path):
    code, out = run_doctor(tmp_path, {}, "--skip-fixtures")
    assert code == 0, out
    assert "result: OK" in out
    assert "bug-hunt" in out and "conventions" in out


def test_given_kit_reviewer_without_kit_then_reported_skipped(tmp_path):
    code, out = run_doctor(tmp_path, {"reviewers": ["kit"], "optional": {"dotnet-claude-kit": False}}, "--skip-fixtures")
    assert code == 0, out
    assert "kit" in out and "skipped" in out and "not installed" in out


def test_given_code_review_workflow_without_mcp_then_reported_skipped(tmp_path):
    answers = {"reviewers": ["code-review-workflow"], "optional": {"dotnet-claude-kit": True, "roslyn-mcp": False}}
    code, out = run_doctor(tmp_path, answers, "--skip-fixtures")
    assert code == 0, out
    assert "code-review-workflow" in out and "roslyn-mcp" in out


def test_given_invalid_profile_then_exit_1(tmp_path):
    code, out = run_doctor(tmp_path, {"tracker": "none", "qa": {"evidence": "work-item"}}, "--skip-fixtures")
    assert code == 1
    assert "invalid:" in out


def test_given_every_profile_value_then_an_adapter_resolves(tmp_path):
    answers = {"tracker": "azure-boards", "scm": "azure-repos", "architecture": "vertical",
               "qa": {"owner": "qa-team", "evidence": "work-item"},
               "stack": {"data": "cosmos", "api": "graphql", "messaging": "wolverine", "errors": "result", "local_run": "docker"}}
    code, out = run_doctor(tmp_path, answers, "--skip-fixtures")
    assert code == 0, out
    assert "MISSING" not in out


def test_given_fixtures_then_both_checkers_pass(tmp_path):
    code, out = run_doctor(tmp_path, {})
    assert code == 0, out
    assert "plan     ok" in out and "review   ok" in out


def test_given_checks_without_jev_then_conventions_only(tmp_path):
    answers = {"checks": [{"id": "ct", "rule": "Propagate CancellationToken", "severity": "high"}]}
    code, out = run_doctor(tmp_path, answers, "--skip-fixtures")
    assert code == 0, out
    assert "checks" in out and "1 rule enforced by conventions only" in out


def test_given_checks_with_jev_then_scored_by_jev(tmp_path):
    answers = {"optional": {"jev": True}, "checks": [
        {"id": "ct", "rule": "Propagate CancellationToken", "severity": "high"},
        {"id": "now", "rule": "No DateTime.Now", "severity": "medium"}]}
    code, out = run_doctor(tmp_path, answers, "--skip-fixtures")
    assert code == 0, out
    assert "2 rules scored by jev" in out
    assert "jev " in out and "via the jev MCP" in out


def test_given_key_in_env_then_doctor_names_the_source_not_the_value(tmp_path):
    code, out = run_doctor(tmp_path, {"optional": {"jev": True}}, "--skip-fixtures", key="placeholder-key-for-tests")
    assert code == 0, out
    assert "jev: key from env" in out
    assert "placeholder-key-for-tests" not in out


def test_given_jev_enabled_without_key_then_doctor_says_so(tmp_path):
    code, out = run_doctor(tmp_path, {"optional": {"jev": True}}, "--skip-fixtures")
    assert code == 0, out
    assert "jev: no key found" in out


def test_given_defaults_then_jev_not_configured(tmp_path):
    code, out = run_doctor(tmp_path, {}, "--skip-fixtures")
    assert "jev: not configured" in out


def test_given_stage_checks_then_doctor_lists_them(tmp_path):
    answers = {"stage_checks": {"test": [{"id": "green", "prompt": "Did every suite pass?", "on_fail": "stop"},
                                         {"id": "e2e", "prompt": "Did e2e run?"}]}}
    code, out = run_doctor(tmp_path, answers, "--skip-fixtures")
    assert code == 0, out
    assert "stage checks (answered by Claude):" in out
    assert "test" in out and "2 checks, 1 stop on fail" in out
