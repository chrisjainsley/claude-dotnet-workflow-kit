"""doctor.py reports adapters, reviewers and fixture health for a profile without the claude CLI."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"


def run_doctor(tmp_path, answers, *extra):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(answers), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
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
