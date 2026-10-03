"""The progress-bar hooks ship with the plugin and agree with the skills they watch."""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER = REPO_ROOT / "hooks" / "register.tsx"


def register_text():
    return REGISTER.read_text(encoding="utf-8")


def skill_text(name):
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_given_plugin_then_hooks_module_and_types_ship():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert hooks == {"modules": ["./register.tsx"]}
    assert REGISTER.exists()
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (REPO_ROOT / manifest["types"]).exists()


def test_given_state_contract_then_keyed_by_the_plugin_name():
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    plugins = set(re.findall(r"plugin: '([^']+)'", register_text()))
    assert plugins == {manifest["name"]}
    assert f"'{manifest['name']}':" in (REPO_ROOT / "types" / "index.d.ts").read_text(encoding="utf-8")


def test_given_goals_then_next_ends_each_half_with_the_goal_text():
    goals = dict(re.findall(r"^\s*(review|complete): '([^']+)',$", register_text(), re.M))
    assert set(goals) == {"review", "complete"}
    text = skill_text("next")
    for goal in goals.values():
        assert f"/goal {goal}`" in text, f"next must name the goal the hooks set: {goal}"
        assert f'"{goal} for <item>."' in text, f"next must end a half with: {goal}"


def test_given_state_fields_the_bar_reads_then_skills_write_them():
    text = register_text()
    for field in ("shortTitle", "order", "blocked", "waiting", "artifactUrl"):
        assert field in text
    start, plan, nxt = skill_text("start"), skill_text("plan"), skill_text("next")
    assert "shortTitle" in start and "--order" in start, "start must write shortTitle and order"
    assert "artifactUrl" in plan, "plan must record its page in the state file"
    for needle in ("current.blocked", "current.detail", "extra_stages", "--order", "stages.<id>.waiting"):
        assert needle in nxt, f"next must document {needle}"


def test_given_repo_then_hooks_name_no_owner_paths():
    text = register_text()
    assert "dev-mods" not in text, "hooks must not point at a local dev-mods folder"


def test_given_hooks_then_closed_items_read_done_and_leave_after_a_day():
    text = register_text()
    assert "!!data.closed || stageDone(stages, stage.id)" in text
    assert "now - Date.parse(data.closed.at) > REMOVE_MS" in text
    assert "const REMOVE_MS = 24 * 60 * 60 * 1000" in text


def test_given_hooks_then_the_closing_script_runs_on_a_slow_timer():
    text = register_text()
    assert "/scripts/close_items.py" in text
    assert (REPO_ROOT / "scripts" / "close_items.py").is_file()
    assert "$.clock.every(CLOSE_MS, () => void closeItems($))" in text
    assert "const CLOSE_MS = 10 * 60 * 1000" in text


def test_given_more_rows_than_the_cap_then_live_items_sort_ahead_of_complete_ones():
    text = register_text()
    sort = text[text.index("found.sort("):text.index("const seen = new Set")]
    assert sort.index("isCurrentBranch") < sort.index("isComplete(a.row)") < sort.index("b.mtime - a.mtime")


def test_given_done_group_then_dismiss_all_hides_every_done_row():
    text = register_text()
    assert 'label="Dismiss all"' in text
    assert "...group.items.map(row => row.slug)" in text


def test_given_progress_done_then_the_current_item_closes_by_hand():
    text = register_text()
    assert "e.args.trim() === 'done'" in text
    assert "reason: 'manual'" in text
