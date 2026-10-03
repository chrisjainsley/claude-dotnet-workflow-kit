#!/usr/bin/env python
"""Close finished pipeline items and delete them a day later.

    python close_items.py --repo <git common dir> [--dir <pipeline dir>] [--now <ISO time>]

An item closes when its pull request merged or closed (asked of `gh`, or `az` for an
Azure Repos URL), or when it was started in a worktree that no longer exists, which is
what archiving a worktree session leaves behind. A closed item records
`closed: {reason, at}` in its state file; one day after `closed.at` the file is deleted.
Only items of the repository at --repo are checked; deleting covers every closed file.
A missing CLI or a failed call skips that item. Prints one line per change.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REMOVE_AFTER = timedelta(days=1)
DEFAULT_DIR = Path.home() / ".claude" / "dotnet-workflow-kit" / "pipeline"


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv, cwd=None):
    """stdout of a command, or None when it is missing or fails."""
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=60)
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
    out = run(["git", "--git-dir", str(repo), *args])
    return out.splitlines() if out else []


def local_branches(repo):
    return set(git_lines(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads"))


def worktree_branches(repo):
    """Branches checked out in a worktree that still exists on disk."""
    found, path = set(), None
    for line in git_lines(repo, "worktree", "list", "--porcelain"):
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/") and path and Path(path).exists():
            found.add(line[18:])
    return found


def same_repo(a, b):
    return Path(a).resolve() == Path(b).resolve()


def closing_reason(data, repo, worktrees, now):
    url = pr_url(data)
    if url:
        state = pr_state(url)
        if state and state[0] in ("merged", "closed"):
            return state[0], state[1] or iso(now)
    if data.get("worktree") is True and data.get("branch") and data["branch"] not in worktrees:
        return "archived", iso(now)
    return None


def close_items(directory, repo, now):
    """Close this repository's finished items, then delete closed files past a day. Returns the changes."""
    changes, branches, worktrees = [], local_branches(repo), worktree_branches(repo)
    for path in sorted(Path(directory).glob("*.json")):
        if "-checks" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        closed = data.get("closed")
        if closed:
            if now - parse_time(closed["at"]) > REMOVE_AFTER:
                path.unlink()
                changes.append(f"removed {path.name}")
            continue
        mine = same_repo(data["repo"], repo) if data.get("repo") else data.get("branch") in branches
        if not mine:
            continue
        found = closing_reason(data, repo, worktrees, now)
        if found:
            data["closed"] = {"reason": found[0], "at": found[1]}
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            changes.append(f"closed {path.name}: {found[0]}")
    return changes


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
