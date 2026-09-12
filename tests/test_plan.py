import json
import re
from pathlib import Path

import pytest

from conftest import (
    BUILD_PLAN_PY,
    CHECK_PLAN_PY,
    FIXTURES_DIR,
    run_py,
)


def test_given_fixture_matches_exemplar(plan_fixture_text):
    checked_in = (FIXTURES_DIR / "plan.md").read_text(encoding="utf-8")
    assert checked_in == plan_fixture_text


def test_given_exemplar_fixture_then_check_passes(plan_fixture_path):
    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)
    assert code == 0, out + err
    assert "OK" in out


def test_given_over_budget_section_then_exit1(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    filler = " word" * 200
    text = text.replace(
        "Today the credit is per account, so a second account is another $10.",
        "Today the credit is per account, so a second account is another $10." + filler,
        1,
    )
    plan_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)

    assert code == 1
    assert "Requirement" in out
    assert "OVER" in out


def test_given_missing_section_then_exit1(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    text = re.sub(r"\n## Domain\n.*?(?=\n## Application\n)", "\n", text, flags=re.S)
    plan_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)

    assert code == 1
    assert "sections must be exactly" in out


def test_given_question_with_two_recommended_then_exit1(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    text = text.replace(
        "   - [ ] **Include now.** Adds a B2C policy PR, a connector model field and a second payer key to this stack.",
        "   - [x] **Include now.** Adds a B2C policy PR, a connector model field and a second payer key to this stack.",
        1,
    )
    plan_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)

    assert code == 1
    assert "exactly one [x]" in out


def test_given_fixture_then_build_writes_html_with_question_form(tmp_path, plan_fixture_text):
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(plan_fixture_text, encoding="utf-8")
    out_path = tmp_path / "plan.html"

    code, out, err = run_py(BUILD_PLAN_PY, plan_path, "--out", out_path)

    assert code == 0, out + err
    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert '<form class="qform"' in html
    assert "Include the durable sign-in identity in this story?" in html
    assert "Backfill payer claims for grants PR 3081 already issued on sandbox and dev?" in html
    assert "Anything else to preserve or avoid?" in html
    assert 'type="radio"' in html


def test_given_vertical_profile_then_check_expects_slice_sections(tmp_path, plan_fixture_path):
    profile_path = tmp_path / "vertical-profile.json"
    profile_path.write_text(json.dumps({"architecture": "vertical"}), encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path, "--profile", profile_path)

    assert code == 1
    assert "Slice" in out


VERTICAL_FIXTURE_PATH = FIXTURES_DIR / "plan-vertical.md"
VERTICAL_PROFILE_PATH = FIXTURES_DIR / "profile-vertical.json"
VERTICAL_SECTIONS = [
    "Context", "Requirement", "Specs", "Slice", "Persistence", "Integration",
    "Endpoint", "Tests", "Decisions", "Risks and rollout", "Open questions",
]


def test_given_vertical_fixture_then_check_passes():
    code, out, err = run_py(CHECK_PLAN_PY, VERTICAL_FIXTURE_PATH, "--profile", VERTICAL_PROFILE_PATH)

    assert code == 0, out + err
    assert "OK" in out


def test_given_vertical_fixture_then_build_renders_all_sections(tmp_path):
    out_path = tmp_path / "plan-vertical.html"

    code, out, err = run_py(BUILD_PLAN_PY, VERTICAL_FIXTURE_PATH, "--out", out_path)

    assert code == 0, out + err
    html = out_path.read_text(encoding="utf-8")
    for name in VERTICAL_SECTIONS:
        assert f"<h2>{name}</h2>" in html, name


def test_given_vertical_fixture_with_clean_profile_then_check_fails():
    code, out, err = run_py(CHECK_PLAN_PY, VERTICAL_FIXTURE_PATH)

    assert code == 1
    assert "sections must be exactly" in out
