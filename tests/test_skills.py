"""Every shipped skill has a well-formed SKILL.md and the pieces its workflow names."""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("visual-plan", "visual-review", "start-ticket", "qa-report", "qa-notes", "mega-review", "next")
FRONT_MATTER = re.compile(r"^---\nname: (?P<name>[a-z0-9-]+)\ndescription: (?P<description>.+?)\n---\n", re.S)


def skill_text(name):
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SKILLS)
def test_given_skill_then_front_matter_names_it(name):
    match = FRONT_MATTER.match(skill_text(name))
    assert match, f"{name}: SKILL.md must start with name and description front matter"
    assert match.group("name") == name
    assert len(match.group("description").split()) >= 20, f"{name}: description too short to trigger on"


@pytest.mark.parametrize("name", SKILLS)
def test_given_skill_then_it_resolves_the_profile(name):
    text = skill_text(name)
    assert "## Profile" in text, f"{name}: needs a Profile section"
    assert "scripts/profile.py" in text, f"{name}: must resolve the profile through scripts/profile.py"


@pytest.mark.parametrize("name", SKILLS)
def test_given_skill_then_no_owner_specifics(name):
    text = skill_text(name)
    owner_name = "Chr" + "is"
    for banned in ("efficient-fable", "sandbox trigger", "qa required", "QA Ready", "Blue " + "Steel", owner_name):
        assert banned not in text, f"{name}: contains owner-specific text {banned!r}"


def test_given_mega_review_then_built_in_reviewers_ship():
    reviewers = REPO_ROOT / "skills" / "mega-review" / "reviewers"
    for name in ("bug-hunt", "conventions"):
        path = reviewers / f"{name}.md"
        assert path.exists(), f"missing built-in reviewer {name}"
        assert len(path.read_text(encoding="utf-8").split()) >= 250


def test_given_next_then_stage_table_names_kit_skills_only():
    text = skill_text("next")
    for kit_skill in ("start-ticket", "visual-plan", "mega-review", "visual-review"):
        assert f"dotnet-workflow-kit:{kit_skill}" in text
    assert "dotnet-workflow-kit/pipeline" in text, "state file must live under ~/.claude/dotnet-workflow-kit/pipeline"
    for field in ("pipeline.execute", "pipeline.resolve_comments", "pipeline.qa"):
        assert field in text, f"next must read {field} from the profile"


def test_given_tracker_skills_then_they_defer_to_adapters():
    for name in ("start-ticket", "qa-report", "qa-notes"):
        text = skill_text(name)
        assert "adapters/tracker/" in text, f"{name}: tracker calls must go through adapters/tracker/<tracker>.md"
