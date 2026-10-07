#!/usr/bin/env python
"""Close finished pipeline items and delete them a day later.

    python close_items.py --repo <git common dir> [--dir <pipeline dir>] [--now <ISO time>]

An item closes when its pull request merged or closed (asked of `gh`, or `az` for an
Azure Repos URL), or when the worktree it was started in no longer exists, which is
what archiving a worktree session leaves behind. An item the progress bar adopted
(`adopted: true`, a branch no skill has taken over) also closes when its branch is
deleted, or when its file has gone untouched for a week, and its file is deleted at
once when a skill wrote another file for the same branch. A closed item records
`closed: {reason, at, prAt}` in its state file, `at` being when this script saw it
close; one day after `closed.at` the file is deleted. Only items of the repository at
--repo are checked; deleting covers every closed file. A missing CLI, a failed call or
a malformed file skips that item. Prints one line per change.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REMOVE_AFTER = timedelta(days=1)
# The progress bar rewrites an adopted item's file while its session works, so a week untouched is idle.
IDLE_AFTER = timedelta(days=7)
DEFAULT_DIR = Path.home() / ".claude" / "dotnet-workflow-kit" / "pipeline"


def parse_time(text):
    """An ISO time as an aware datetime; naive times read as UTC, extra fraction digits are cut."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00"))
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv, cwd=None):
    """stdout of a command, or None when it is missing or fails."""
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def pr_url(data):
    stages = data.get("stages") or {}
    for key in ("pullRequest", "pull_request"):
        url = (stages.get(key) or {}).get("url")
        if url:
            return url
    return ""


def pr_state(url):
    """('merged' | 'closed' | 'open', ISO time or None), or None when it cannot be told."""
    azure = re.search(r"/pullrequest/(\d+)", url, re.I)
    if azure:
        out = run(["az", "repos", "pr", "show", "--id", azure.group(1), "--query", "{status:status,closed:closedDate}", "-o", "json"])
        if out is None:
            return None
        info = json.loads(out)
        status = {"completed": "merged", "abandoned": "closed"}.get(info.get("status"), "open")
        return status, info.get("closed")
    out = run(["gh", "pr", "view", url, "--json", "state,mergedAt,closedAt"])
    if out is None:
        return None
    info = json.loads(out)
    state = (info.get("state") or "").upper()
    if state == "MERGED":
        return "merged", info.get("mergedAt")
    if state == "CLOSED":
        return "closed", info.get("closedAt")
    return "open", None


def git_lines(repo, *args):
    """The command's output lines, or None when git failed."""
    out = run(["git", "--git-dir", str(repo), *args])
    return None if out is None else out.splitlines()


def local_branches(repo):
    return set(git_lines(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads") or [])


def worktree_branches(repo):
    """Branches checked out in a worktree that still exists on disk, or None when git failed."""
    lines = git_lines(repo, "worktree", "list", "--porcelain")
    if lines is None:
        return None
    found, path = set(), None
    for line in lines:
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/") and path and Path(path).exists():
            found.add(line[18:])
    return found


def same_repo(a, b):
    return Path(a).resolve() == Path(b).resolve()


def worktree_gone(data, worktrees):
    """Whether the worktree the item started in is gone; never true when it cannot be told."""
    recorded = data.get("worktree")
    if isinstance(recorded, str) and recorded:
        return not Path(recorded).exists()
    # Files from before the path was recorded carry only `true`: judge by the branch.
    return recorded is True and worktrees is not None and bool(data.get("branch")) and data["branch"] not in worktrees


def closing_reason(data, worktrees, branches=None, idle=False):
    """(reason, the PR's own close time or None), or None while the item is open."""
    url = pr_url(data)
    if url:
        state = pr_state(url)
        if state and state[0] in ("merged", "closed"):
            return state
    if worktree_gone(data, worktrees):
        return "archived", None
    if data.get("adopted") is True:
        # An empty set means git failed, so a deleted branch cannot be told.
        if branches and data.get("branch") and data["branch"] not in branches:
            return "deleted", None
        if idle:
            return "idle", None
    return None


def write_json(path, data):
    """Replaces the file in one step, so a reader never sees it half written."""
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def close_items(directory, repo, now):
    """Close this repository's finished items, then delete closed files past a day. Returns the changes."""
    changes, branches, worktrees = [], local_branches(repo), worktree_branches(repo)
    taken = kit_branches(directory, repo, branches)
    for path in sorted(Path(directory).glob("*.json")):
        if "-checks" in path.name:
            continue
        try:
            change = close_one(path, repo, branches, worktrees, now, taken)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue  # A half-written or foreign file: leave it for the next run.
        if change:
            changes.append(change)
    return changes


def kit_branches(directory, repo, branches):
    """Branches of this repository a skill wrote a file for, which an adopted file for the same branch duplicates."""
    found = set()
    for path in Path(directory).glob("*.json"):
        if "-checks" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            mine = same_repo(data["repo"], repo) if data.get("repo") else data.get("branch") in branches
            if data.get("adopted") is not True and data.get("branch") and mine:
                found.add(data["branch"])
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return found


def close_one(path, repo, branches, worktrees, now, taken=frozenset()):
    data = json.loads(path.read_text(encoding="utf-8"))
    closed = data.get("closed")
    if closed:
        if now - parse_time(closed["at"]) > REMOVE_AFTER:
            path.unlink()
            return f"removed {path.name}"
        return None
    mine = same_repo(data["repo"], repo) if data.get("repo") else data.get("branch") in branches
    if not mine:
        return None
    if data.get("adopted") is True and data.get("branch") in taken:
        path.unlink()
        return f"removed {path.name}: taken over"
    idle = now - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > IDLE_AFTER
    found = closing_reason(data, worktrees, branches, idle)
    if not found:
        return None
    # The day counts from when the item was seen closed, so a PR merged long ago still shows done for a day.
    data["closed"] = {"reason": found[0], "at": iso(now), **({"prAt": found[1]} if found[1] else {})}
    write_json(path, data)
    return f"closed {path.name}: {found[0]}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="the repository's git common dir")
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="the pipeline state folder")
    ap.add_argument("--now", help="the time to judge by, ISO 8601 (default: now)")
    args = ap.parse_args(argv)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if not Path(args.dir).is_dir():
        return 0
    for line in close_items(args.dir, args.repo, now):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
