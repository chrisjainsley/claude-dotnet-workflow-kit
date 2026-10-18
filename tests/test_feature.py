"""The feature page: its check, its page and the story order feature_order.py works out."""
import json

import pytest

import feature_order
import kit_profile as profile_mod
from conftest import FIXTURES_DIR, REPO_ROOT, run_py

FEATURE_FIXTURE = FIXTURES_DIR / "feature.md"
FEATURE_DIR = REPO_ROOT / "skills" / "feature"
CHECK_FEATURE_PY = FEATURE_DIR / "scripts" / "check_feature.py"
BUILD_FEATURE_PY = FEATURE_DIR / "scripts" / "build_feature.py"
FEATURE_ORDER_PY = REPO_ROOT / "scripts" / "feature_order.py"


def profile(**overrides):
    prof, _ = profile_mod.migrate(overrides)
    return prof


def stories(*rows):
    return [{"key": k, "title": f"story {k}", "depends": list(deps), "size": "small"} for k, deps in rows]


def write_feature(tmp_path, rows, specs=None, name="feature.md"):
    table = "\n".join(f"| {k} | story {k} | {', '.join(d) or '-'} | small |" for k, d in rows)
    blocks = "\n\n".join(
        f"```gherkin\nFeature: {k} story\n\n  Scenario: it works\n    Given a\n    Then b\n```"
        for k in (specs if specs is not None else [k for k, _ in rows])
    )
    text = FEATURE_FIXTURE.read_text(encoding="utf-8")
    head, rest = text.split("## Stories", 1)
    tail = rest.split("## Delivery order", 1)[1]
    body = (f"{head}## Stories\n\n| Key | Story | Depends on | Size |\n|---|---|---|---|\n{table}\n\n"
            f"## Story specs\n\n{blocks}\n\n## Delivery order{tail}")
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_given_fixture_then_check_passes():
    code, out, err = run_py(CHECK_FEATURE_PY, str(FEATURE_FIXTURE))
    assert code == 0, out + err
    assert "stories 4/12" in out


def test_given_fixture_then_waves_follow_dependencies():
    result, problems = feature_order.load(FEATURE_FIXTURE, profile())
    assert problems == []
    assert result["waves"] == [["S1"], ["S2", "S3"], ["S4"]]
    assert result["stacking"] == "base"


def test_given_one_parent_and_base_stacking_then_child_branches_from_parent():
    plan = {e["key"]: e for e in feature_order.delivery(stories(("S1", []), ("S2", ["S1"])), "base", "main")}
    assert plan["S1"] == {**plan["S1"], "base": "main", "start": "now", "stack": "none"}
    assert plan["S2"]["base_story"] == "S1" and plan["S2"]["base"] is None
    assert plan["S2"]["start"] == "approved" and plan["S2"]["stack"] == "base"


def test_given_stacking_off_then_dependents_wait_for_merge_on_base_branch():
    plan = {e["key"]: e for e in feature_order.delivery(stories(("S1", []), ("S2", ["S1"])), "off", "main")}
    assert plan["S2"]["base"] == "main" and plan["S2"]["base_story"] is None
    assert plan["S2"]["start"] == "merged" and plan["S2"]["stack"] == "none"


def test_given_two_dependencies_then_story_waits_for_both_to_merge():
    plan = {e["key"]: e for e in feature_order.delivery(
        stories(("S1", []), ("S2", []), ("S3", ["S1", "S2"])), "gh-stack", "main")}
    assert plan["S3"]["start"] == "merged" and plan["S3"]["base"] == "main"


def test_given_linear_chain_then_gh_stack_links_it():
    plan = {e["key"]: e for e in feature_order.delivery(
        stories(("S1", []), ("S2", ["S1"]), ("S3", ["S2"])), "gh-stack", "main")}
    assert plan["S2"]["stack"] == "gh-stack" and plan["S3"]["stack"] == "gh-stack"


def test_given_siblings_then_gh_stack_falls_back_to_base():
    """`gh stack link` retargets sibling bases, so a parent with two stacked children
    and everything below them keep their bases by hand."""
    plan = {e["key"]: e for e in feature_order.delivery(
        stories(("S1", []), ("S2", ["S1"]), ("S3", ["S1"]), ("S4", ["S2"])), "gh-stack", "main")}
    assert [plan[k]["stack"] for k in ("S2", "S3", "S4")] == ["base", "base", "base"]


@pytest.mark.parametrize("rows,needle", [
    ((("S1", ["S2"]), ("S2", ["S1"])), "cycle"),
    ((("S1", ["S9"]),), "unknown story S9"),
    ((("S1", ["S1"]),), "depends on itself"),
    ((("X1", []),), "must look like S1"),
])
def test_given_bad_dependencies_then_check_fails(tmp_path, rows, needle):
    path = write_feature(tmp_path, rows)
    code, out, err = run_py(CHECK_FEATURE_PY, str(path))
    assert code == 1
    assert needle in out


def test_given_story_without_specs_then_check_fails(tmp_path):
    path = write_feature(tmp_path, (("S1", []), ("S2", ["S1"])), specs=["S1"])
    code, out, err = run_py(CHECK_FEATURE_PY, str(path))
    assert code == 1
    assert "Feature: S2" in out


def test_given_thirteen_stories_then_check_says_split(tmp_path):
    path = write_feature(tmp_path, [(f"S{i}", []) for i in range(1, 14)])
    code, out, err = run_py(CHECK_FEATURE_PY, str(path))
    assert code == 1
    assert "split the feature" in out


def test_given_fixture_then_page_renders_as_feature(tmp_path):
    out_path = tmp_path / "feature.html"
    code, out, err = run_py(BUILD_FEATURE_PY, str(FEATURE_FIXTURE), "--out", str(out_path))
    assert code == 0, err
    page = out_path.read_text(encoding="utf-8")
    assert '<span class="kind">Feature' in page
    assert "<title>Feature - Expiring loyalty points</title>" in page
    assert 'class="onion"' not in page, "a feature page has no architecture layers"
    assert "1 answerable questions" in out
    assert "create the stories" in page and "Revise the feature" in page
    assert "start implementing" not in page


def test_given_briefs_then_each_names_next_and_its_start(tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps({"S1": "#121", "S2": "#122", "S3": "#123", "S4": "#124"}), encoding="utf-8")
    code, out, err = run_py(FEATURE_ORDER_PY, str(FEATURE_FIXTURE), "--briefs", "--items", str(items),
                            "--page", "https://example.test/feature")
    assert code == 0, err
    assert out.count("/dotnet-workflow-kit:next #") == 4
    assert "Branch from the branch of S1 (#121)" in out
    assert "Start once S2's review is approved" in out
    assert "https://example.test/feature" in out


def test_given_briefs_without_an_id_then_exit1(tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps({"S1": "#121"}), encoding="utf-8")
    code, out, err = run_py(FEATURE_ORDER_PY, str(FEATURE_FIXTURE), "--briefs", "--items", str(items))
    assert code == 1
    assert "no id for S2" in err


def test_given_inline_specs_then_brief_carries_the_gherkin(tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps({k: f"expiry-{k.lower()}" for k in ("S1", "S2", "S3", "S4")}), encoding="utf-8")
    code, out, err = run_py(FEATURE_ORDER_PY, str(FEATURE_FIXTURE), "--briefs", "--items", str(items), "--inline-specs")
    assert code == 0, err
    assert "Feature: S2 Expire unspent points" in out


def test_given_skeleton_then_it_names_every_feature_section():
    skeleton = (FEATURE_DIR / "assets" / "skeleton.md").read_text(encoding="utf-8")
    assert "kind: feature" in skeleton
    for name, _, _ in profile_mod.FEATURE_SECTIONS:
        assert f"## {name}\n" in skeleton
