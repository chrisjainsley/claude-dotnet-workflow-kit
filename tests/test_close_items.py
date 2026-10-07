"""close_items.py closes merged, closed and archived items and deletes them a day later."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

import close_items

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
PR = "https://github.com/example/repo/pull/7"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    git(root, "branch", "feat/item")
    return root / ".git"


@pytest.fixture
def pipeline(tmp_path):
    folder = tmp_path / "pipeline"
    folder.mkdir()
    return folder


def write(folder, name, data):
    path = folder / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def item(**extra):
    return {"branch": "feat/item", "stages": {"start": {"done": True}}, **extra}


def with_pr(state, monkeypatch, at="2026-10-03T10:00:00Z"):
    real = close_items.run

    def fake(argv, cwd=None):
        if argv[0] == "gh":
            return json.dumps({"state": state, "mergedAt": at if state == "MERGED" else None, "closedAt": at})
        return real(argv, cwd)

    monkeypatch.setattr(close_items, "run", fake)


def pr_item():
    return item(stages={"pullRequest": {"done": True, "url": PR}})


def test_given_merged_pr_then_closed_merged_from_now_with_the_merge_time_kept(repo, pipeline, monkeypatch):
    with_pr("MERGED", monkeypatch)
    path = write(pipeline, "item", pr_item())
    assert close_items.close_items(pipeline, repo, NOW) == ["closed item.json: merged"]
    assert json.loads(path.read_text())["closed"] == {
        "reason": "merged", "at": "2026-10-03T12:00:00Z", "prAt": "2026-10-03T10:00:00Z"
    }


def test_given_closed_pr_then_closed_closed(repo, pipeline, monkeypatch):
    with_pr("CLOSED", monkeypatch)
    path = write(pipeline, "item", pr_item())
    close_items.close_items(pipeline, repo, NOW)
    assert json.loads(path.read_text())["closed"]["reason"] == "closed"


def test_given_open_pr_then_unchanged(repo, pipeline, monkeypatch):
    with_pr("OPEN", monkeypatch)
    path = write(pipeline, "item", pr_item())
    before = path.read_text()
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert path.read_text() == before


def test_given_worktree_gone_then_closed_archived(repo, pipeline):
    path = write(pipeline, "item", item(worktree=True))
    close_items.close_items(pipeline, repo, NOW)
    assert json.loads(path.read_text())["closed"] == {"reason": "archived", "at": "2026-10-03T12:00:00Z"}


def test_given_worktree_still_there_then_unchanged(repo, pipeline, tmp_path):
    git(repo.parent, "worktree", "add", "-q", str(tmp_path / "wt"), "feat/item")
    path = write(pipeline, "item", item(worktree=True))
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert "closed" not in json.loads(path.read_text())


def test_given_no_worktree_recorded_then_unchanged(repo, pipeline):
    path = write(pipeline, "item", item())
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert "closed" not in json.loads(path.read_text())


def test_given_item_of_another_repo_then_unchanged(repo, pipeline):
    path = write(pipeline, "item", item(worktree=True, branch="feat/elsewhere"))
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert path.exists()


def test_given_closed_25h_ago_then_deleted(repo, pipeline):
    at = close_items.iso(NOW - timedelta(hours=25))
    path = write(pipeline, "item", item(closed={"reason": "merged", "at": at}))
    assert close_items.close_items(pipeline, repo, NOW) == ["removed item.json"]
    assert not path.exists()


def test_given_closed_23h_ago_then_kept(repo, pipeline):
    at = close_items.iso(NOW - timedelta(hours=23))
    path = write(pipeline, "item", item(closed={"reason": "merged", "at": at}))
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert path.exists()


def test_given_gh_missing_then_skipped(repo, pipeline, monkeypatch):
    real = close_items.run
    monkeypatch.setattr(close_items, "run", lambda argv, cwd=None: None if argv[0] == "gh" else real(argv, cwd))
    path = write(pipeline, "item", pr_item())
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert "closed" not in json.loads(path.read_text())


def test_given_recorded_worktree_path_gone_then_closed_archived(repo, pipeline, tmp_path):
    path = write(pipeline, "item", item(worktree=str(tmp_path / "gone")))
    close_items.close_items(pipeline, repo, NOW)
    assert json.loads(path.read_text())["closed"]["reason"] == "archived"


def test_given_recorded_worktree_path_present_then_unchanged(repo, pipeline, tmp_path):
    path = write(pipeline, "item", item(worktree=str(tmp_path)))
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert "closed" not in json.loads(path.read_text())


def test_given_git_failing_then_nothing_is_archived(repo, pipeline, monkeypatch):
    path = write(pipeline, "item", item(worktree=True, repo=str(repo)))
    monkeypatch.setattr(close_items, "run", lambda argv, cwd=None: None)
    assert close_items.close_items(pipeline, repo, NOW) == []
    assert "closed" not in json.loads(path.read_text())


def test_given_malformed_files_then_the_rest_still_close(repo, pipeline):
    write(pipeline, "a-no-at", item(closed={"reason": "manual"}))
    write(pipeline, "b-list", [1, 2])
    (pipeline / "c-broken.json").write_text("{", encoding="utf-8")
    path = write(pipeline, "d-item", item(worktree=True))
    assert close_items.close_items(pipeline, repo, NOW) == ["closed d-item.json: archived"]
    assert json.loads(path.read_text())["closed"]["reason"] == "archived"


def test_given_azure_seven_digit_time_then_it_parses():
    assert close_items.parse_time("2026-10-03T10:00:00.1234567Z") == datetime(2026, 10, 3, 10, 0, 0, 123456, tzinfo=timezone.utc)


def adopted(**extra):
    return item(adopted=True, **extra)


def age(path, days):
    moment = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (moment, moment))


def test_given_adopted_item_whose_branch_is_deleted_then_closed_deleted(repo, pipeline):
    path = write(pipeline, "gone", adopted(branch="feat/gone", repo=str(repo)))
    close_items.close_items(pipeline, repo, NOW)
    assert json.loads(path.read_text())["closed"] == {"reason": "deleted", "at": "2026-10-03T12:00:00Z"}


def test_given_adopted_item_untouched_for_8_days_then_closed_idle(repo, pipeline):
    path = write(pipeline, "item", adopted(repo=str(repo)))
    age(path, 8)
    close_items.close_items(pipeline, repo, NOW)
    assert json.loads(path.read_text())["closed"]["reason"] == "idle"


def test_given_adopted_item_touched_6_days_ago_then_unchanged(repo, pipeline):
    path = write(pipeline, "item", adopted(repo=str(repo)))
    age(path, 6)
    assert close_items.close_items(pipeline, repo, NOW) == []


def test_given_kit_item_untouched_for_8_days_or_branch_deleted_then_unchanged(repo, pipeline):
    idle = write(pipeline, "item", item(repo=str(repo)))
    age(idle, 8)
    write(pipeline, "gone", item(branch="feat/gone", repo=str(repo)))
    assert close_items.close_items(pipeline, repo, NOW) == []


def test_given_adopted_item_a_skill_took_over_under_another_name_then_deleted(repo, pipeline):
    orphan = write(pipeline, "feat-item", adopted(repo=str(repo)))
    kit = write(pipeline, "PROJ-1", item(repo=str(repo)))
    assert close_items.close_items(pipeline, repo, NOW) == ["removed feat-item.json: taken over"]
    assert not orphan.exists() and kit.exists()
