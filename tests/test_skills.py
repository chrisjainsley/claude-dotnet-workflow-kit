"""Every shipped skill has a well-formed SKILL.md and the pieces its workflow names."""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("start", "plan", "implement", "test", "review", "next")
OLD_NAMES = ("start-ticket", "visual-plan", "mega-review", "qa-report", "visual-review")
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
    assert "scripts/kit_profile.py" in text, f"{name}: must resolve the profile through scripts/kit_profile.py"


@pytest.mark.parametrize("name", SKILLS)
def test_given_skill_then_no_owner_specifics(name):
    text = skill_text(name)
    owner_name = "Chr" + "is"
    for banned in ("efficient-fable", "sandbox trigger", "qa required", "QA Ready", "Blue " + "Steel", owner_name):
        assert banned not in text, f"{name}: contains owner-specific text {banned!r}"


def test_given_review_then_built_in_reviewers_ship():
    reviewers = REPO_ROOT / "skills" / "review" / "reviewers"
    for name in ("bug-hunt", "conventions"):
        path = reviewers / f"{name}.md"
        assert path.exists(), f"missing built-in reviewer {name}"
        assert len(path.read_text(encoding="utf-8").split()) >= 250


def test_given_review_then_sweep_reference_ships():
    sweep = REPO_ROOT / "skills" / "review" / "sweep.md"
    assert sweep.exists(), "the reviewer sweep must live at skills/review/sweep.md"
    text = sweep.read_text(encoding="utf-8")
    for phase in ("Phase 1", "Phase 2", "Phase 3"):
        assert phase in text
    assert "reviewers/bug-hunt.md" in text and "reviewers/conventions.md" in text


def test_given_implement_then_it_runs_the_sweep():
    text = skill_text("implement")
    assert "sweep.md" in text, "implement must run the reviewer sweep from skills/review/sweep.md"
    assert "testing.tdd" in text
    assert "pipeline.execute" in text


def test_given_test_then_it_runs_scenarios_and_reports():
    text = skill_text("test")
    assert "adapters/qa/" in text
    assert "qa.deploy_label" in text
    assert "Unit and integration suites are never QA evidence" in text


def test_given_next_then_stage_table_names_kit_skills_only():
    text = skill_text("next")
    for kit_skill in ("start", "plan", "implement", "test", "review"):
        assert f"dotnet-workflow-kit:{kit_skill}" in text
    assert "dotnet-workflow-kit/pipeline" in text, "state file must live under ~/.claude/dotnet-workflow-kit/pipeline"
    for field in ("pipeline.execute", "pipeline.resolve_comments", "pipeline.qa"):
        assert field in text, f"next must read {field} from the profile"
    for old_key in ("startTicket", "megaReview", "draftPr", "resolveComments"):
        assert old_key in text, f"next must migrate the 0.5.0 state key {old_key}"


@pytest.mark.parametrize("name", SKILLS)
def test_given_skill_then_no_old_skill_name_in_prose(name):
    """Old names survive only inside the description, as trigger phrases."""
    text = skill_text(name)
    body = FRONT_MATTER.sub("", text, count=1)
    for old in OLD_NAMES:
        assert old not in body, f"{name}: body still names the old skill {old!r}"


def test_given_tracker_skills_then_they_defer_to_adapters():
    for name in ("start", "test"):
        text = skill_text(name)
        assert "adapters/tracker/" in text, f"{name}: tracker calls must go through adapters/tracker/<tracker>.md"


@pytest.mark.parametrize("name", SKILLS)
def test_given_skill_then_jev_is_optional_and_documented_once(name):
    text = skill_text(name)
    assert "optional.jev" in text, f"{name}: must gate its Jev touchpoints on optional.jev"
    assert "docs/jev.md" in text, f"{name}: must point at docs/jev.md rather than restate the call shapes"
    assert "kipped" in text, f"{name}: must say Jev is skipped, never failed"


def test_given_sweep_then_it_scores_checks_and_gates():
    text = (REPO_ROOT / "skills" / "review" / "sweep.md").read_text(encoding="utf-8")
    for needle in ("jev_checks.py", "jev_gate", "jev_compare", "sweep.checks", "## Jev", "secret patterns"):
        assert needle in text, f"sweep.md must mention {needle}"
    assert "pipeline/<slug>-checks.json" in text, "checks output must live beside the state file"


def test_given_conventions_reviewer_then_it_reads_profile_checks():
    text = (REPO_ROOT / "skills" / "review" / "reviewers" / "conventions.md").read_text(encoding="utf-8")
    assert "`checks`" in text and "profile: <id>" in text
    assert "## With Jev scores" in text


def test_given_next_then_ci_and_thread_classes_named():
    text = skill_text("next")
    for needle in ("this_branch", "unrelated_infrastructure", "flaky", "needs_code_change", "already_addressed", "jev_screen"):
        assert needle in text


def test_given_test_skill_then_failure_buckets_named():
    text = skill_text("test")
    for needle in ("real_regression", "assertion_changed_by_refactor", "flaky_known", "environment"):
        assert needle in text


def test_given_plan_then_decide_escape_hatches_handled():
    text = skill_text("plan")
    for needle in ("jev_decide", "ask_user", "investigate", "Jev-assisted", "jev_rerank", "jev_screen"):
        assert needle in text


def test_given_jev_doc_then_every_tool_the_skills_call_is_described():
    doc = (REPO_ROOT / "docs" / "jev.md").read_text(encoding="utf-8")
    skills = "\n".join(skill_text(n) for n in SKILLS)
    skills += (REPO_ROOT / "skills" / "review" / "sweep.md").read_text(encoding="utf-8")
    for tool in sorted(set(re.findall(r"jev_[a-z]+", skills))):
        assert tool in doc, f"docs/jev.md must describe {tool}"
    assert "claude mcp add -s user jev" in doc


def test_given_next_then_stage_checks_documented():
    text = skill_text("next")
    assert "## Stage checks" in text and "stage_checks" in text
    for stage in ("start", "plan", "implement", "test", "review", "pull_request"):
        assert f"| {stage} |" in text, f"next must name the evidence for {stage}"
    assert "--stage" in text and "on_fail" in text and "never in place of the user's decision" in text


def test_given_test_and_review_skills_then_same_evidence_syntax():
    root = Path(__file__).resolve().parents[1]
    for rel in ("skills/test/SKILL.md", "skills/review/SKILL.md", "skills/review/assets/skeleton.md"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "evidence/<file>.png" in text, rel
        assert "evidence/<file>.webm" in text, rel
        assert "<redacted>" in text, rel
        assert "`sql` or `text`" in text or "sql or text" in text, rel
        assert "never a markdown table" in text, rel
        assert "case and spacing are ignored" in text, rel
