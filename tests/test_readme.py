import re

import pytest

import profile as profile_mod
from conftest import README_PATH

pytestmark = pytest.mark.skipif(
    not README_PATH.exists(), reason="README.md does not exist yet (written by a parallel agent)"
)

SKILL_NAMES = (
    "visual-plan-doc",
    "visual-review-doc",
    "start-ticket",
    "qa-report",
    "qa-notes",
    "mega-review",
    "next",
)


def readme_text():
    return README_PATH.read_text(encoding="utf-8")


def test_given_profile_defaults_then_readme_lists_every_field():
    text = readme_text()
    keys = profile_mod.flat_keys(profile_mod.DEFAULTS)
    # A dotted key documents itself either spelled out in full (e.g. "testing.tdd")
    # or, when its parent object gets one summary row (e.g. "optional"), by its own
    # leaf name appearing somewhere in that row's prose (e.g. "roslyn-mcp").
    missing = [key for key in keys if key not in text and key.rsplit(".", 1)[-1] not in text]
    assert missing == [], f"README.md is missing these profile fields: {missing}"


def test_given_seven_skills_then_readme_has_a_section_each():
    text = readme_text()
    headings = re.findall(r"(?m)^###\s+(.+)$", text)
    missing = [name for name in SKILL_NAMES if not any(name in heading for heading in headings)]
    assert missing == [], f"README.md is missing an H3 section for: {missing}"


def test_given_readme_then_install_commands_present():
    text = readme_text()
    assert "claude plugin marketplace add" in text
    assert "claude plugin install" in text
