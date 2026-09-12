#!/usr/bin/env python
"""Write the kit's profile from answers, detecting what it can and offering dotnet-claude-kit.

Interactive:      python setup.py
From a file:      python setup.py --profile answers.json [--scope project|user] [--dry-run] [--yes] [--no-install]
Detection only:   python setup.py --detect

The answers file may be partial; anything missing takes the detected value, then the
default. The profile lands at .claude/dotnet-workflow-kit.json in the current project
(scope project, the default) or at ~/.claude/dotnet-workflow-kit.json (scope user).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile import (  # noqa: E402
    BUILT_IN_REVIEWERS, DEFAULTS, ENUMS, FILE_NAME, NEEDS_MCP, OPTIONAL_REVIEWERS,
    deep_merge, get, migrate, needed_skills, put, validate,
)

KIT_PLUGIN = "dotnet-claude-kit"
QUESTIONS = [
    ("user", "Your first name, used in the pages' prose (blank for 'you')", None),
    ("architecture", "Architecture", ENUMS["architecture"]),
    ("testing.tdd", "TDD", ENUMS["testing.tdd"]),
    ("testing.unit", "Unit test framework", ENUMS["testing.unit"]),
    ("testing.integration", "Integration test style", ENUMS["testing.integration"]),
    ("testing.acceptance", "Acceptance tests (BDD)", ENUMS["testing.acceptance"]),
    ("qa.owner", "Who does QA", ENUMS["qa.owner"]),
    ("qa.evidence", "Where QA evidence is posted", ENUMS["qa.evidence"]),
    ("qa.handoff_label", "PR label that hands a PR to QA (blank for none)", None),
    ("qa.deploy_label", "PR label that deploys to the test environment (blank for none)", None),
    ("qa.environment", "Name of the environment QA runs against", None),
    ("tracker", "Work item tracker", ENUMS["tracker"]),
    ("tracker_project", "Tracker project (Azure Boards project, owner/repo, or Jira key)", None),
    ("scm", "Source control", ENUMS["scm"]),
    ("base_branch", "Base branch PRs target", None),
    ("branch_pattern", "Branch naming pattern, must contain {slug}", None),
    ("stack.data", "Data access", ENUMS["stack.data"]),
    ("stack.api", "API style", ENUMS["stack.api"]),
    ("stack.messaging", "Messaging", ENUMS["stack.messaging"]),
    ("stack.errors", "Error handling", ENUMS["stack.errors"]),
    ("stack.local_run", "How the system runs locally", ENUMS["stack.local_run"]),
    ("pipeline.execute", "Command the pipeline runs for the Execute stage (blank: implement the plan by hand)", None),
    ("pipeline.resolve_comments", "Command for the Resolve comments stage (blank: built-in scm adapter steps)", None),
    ("pipeline.qa", "Command for the QA stage (blank: run the plan's Specs manually)", None),
    ("reviewers", "Extra mega-review reviewers, comma separated (" + ", ".join(OPTIONAL_REVIEWERS) + ")", None),
    ("artifacts", "Is the Claude Artifact tool available (yes/no)", None),
]


def run(*cmd, check=False):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)
    except OSError:
        return None


def installed_plugins():
    out = run("claude", "plugin", "list")
    if out is None or out.returncode != 0:
        return {}
    plugins, current = {}, None
    for line in out.stdout.splitlines():
        m = re.match(r"\s*[❯>-]?\s*([\w.-]+)@([\w.-]+)\s*$", line)
        if m:
            current = m.group(1)
            plugins.setdefault(current, {"marketplace": m.group(2), "enabled": False})
        elif current and "Status" in line:
            plugins[current]["enabled"] = plugins[current]["enabled"] or "enabled" in line
    return plugins


def marketplace_source(name):
    out = run("claude", "plugin", "marketplace", "list")
    if out is None or out.returncode != 0:
        return None
    block = re.search(rf"{re.escape(name)}\s*\n\s*Source:\s*(.+)", out.stdout)
    if not block:
        return None
    m = re.search(r"\(([^)]+)\)", block.group(1))
    return m.group(1) if m else block.group(1).strip()


def has_roslyn_mcp():
    out = run("claude", "mcp", "list")
    return bool(out and out.returncode == 0 and re.search(r"roslyn", out.stdout, re.I))


def git_remote_host():
    out = run("git", "remote", "get-url", "origin")
    if out is None or out.returncode != 0:
        return None
    url = out.stdout.strip()
    if "github.com" in url:
        return "github"
    if "dev.azure.com" in url or "visualstudio.com" in url:
        return "azure-repos"
    return None


def detect():
    plugins = installed_plugins()
    found = {
        "scm": git_remote_host(),
        "az": shutil.which("az") is not None,
        "gh": shutil.which("gh") is not None,
        "claude": shutil.which("claude") is not None,
        "plugins": sorted(plugins),
        KIT_PLUGIN: plugins.get(KIT_PLUGIN, {}).get("enabled", False),
        "codex": any(name.startswith("codex") for name in plugins),
        "roslyn-mcp": has_roslyn_mcp(),
    }
    guess = {}
    if found["scm"]:
        guess["scm"] = found["scm"]
    if found["az"] and not found["gh"]:
        guess["tracker"] = "azure-boards"
    elif found["gh"] and found["scm"] == "github":
        guess["tracker"] = "github-issues"
    guess["optional"] = {KIT_PLUGIN: found[KIT_PLUGIN], "codex": found["codex"], "roslyn-mcp": found["roslyn-mcp"]}
    return found, guess


def ask(prompt, default, choices=None):
    hint = f" [{'/'.join(choices)}]" if choices else ""
    shown = f" ({default})" if default not in (None, "") else ""
    while True:
        raw = input(f"{prompt}{hint}{shown}: ").strip()
        if not raw:
            return default
        if choices and raw not in choices:
            print(f"  choose one of: {', '.join(choices)}")
            continue
        return raw


def interactive(base):
    answers = {}
    for key, prompt, choices in QUESTIONS:
        current = get(base, key)
        if key == "reviewers":
            current = ", ".join(r for r in current if r not in BUILT_IN_REVIEWERS)
        if key == "artifacts":
            current = "yes" if current else "no"
        value = ask(prompt, current, choices)
        if key == "reviewers":
            value = [r.strip() for r in str(value).split(",") if r.strip()]
        if key == "artifacts":
            value = str(value).lower() in ("y", "yes", "true", "1")
        put(answers, key, value)
    return answers


def offer_install(profile, found, assume_yes, allow_install):
    needed = needed_skills(profile)
    for skill, mcp in NEEDS_MCP.items():
        if skill in needed and not found.get(mcp):
            print(f"note: {skill} needs the Roslyn MCP server, which was not found; it stays in the profile but will be skipped")
    if not needed:
        print(f"recommended: {KIT_PLUGIN} (not required by your answers)")
        return
    if found.get(KIT_PLUGIN):
        print(f"{KIT_PLUGIN} is installed and provides: {', '.join(needed)}")
        return
    print(f"{KIT_PLUGIN} provides skills your answers rely on: {', '.join(needed)}")
    if not allow_install:
        print("skipping install (--no-install); those skills will be reported as skipped")
        return
    if not (assume_yes or input("Install it now? [y/N]: ").strip().lower() in ("y", "yes")):
        return
    source = marketplace_source(KIT_PLUGIN) or "codewithmukesh/dotnet-claude-kit"
    print(f"adding marketplace {source}")
    added = run("claude", "plugin", "marketplace", "add", source)
    if added is None or added.returncode not in (0,) and "already" not in (added.stderr + added.stdout):
        print(f"marketplace add failed: {(added.stderr if added else 'claude not found').strip()}")
        return
    installed = run("claude", "plugin", "install", f"{KIT_PLUGIN}@{KIT_PLUGIN}")
    if installed is None or installed.returncode != 0:
        print(f"install failed: {(installed.stderr if installed else 'claude not found').strip()}")
        return
    print(f"installed {KIT_PLUGIN}; restart Claude Code to load it")
    found[KIT_PLUGIN] = True


def target_path(scope):
    return (Path.home() if scope == "user" else Path.cwd()) / ".claude" / FILE_NAME


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", help="answers file (partial JSON); omit for interactive prompts")
    ap.add_argument("--scope", choices=("project", "user"), default="project")
    ap.add_argument("--dry-run", action="store_true", help="print the profile, write nothing")
    ap.add_argument("--yes", "-y", action="store_true", help="accept the dotnet-claude-kit install offer without asking")
    ap.add_argument("--no-install", action="store_true", help="never run claude plugin install")
    ap.add_argument("--detect", action="store_true", help="print what setup detects and exit")
    args = ap.parse_args()

    found, guess = detect()
    if args.detect:
        print(json.dumps(found, indent=2))
        return 0

    base = deep_merge(DEFAULTS, guess)
    existing = target_path(args.scope)
    if existing.exists():
        base = deep_merge(base, json.loads(existing.read_text(encoding="utf-8")))

    if args.profile:
        answers = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    elif sys.stdin.isatty():
        answers = interactive(base)
    else:
        print("no --profile and no terminal to ask questions in", file=sys.stderr)
        return 2

    profile, _ = migrate(deep_merge(base, answers))
    profile["optional"] = deep_merge(profile.get("optional", {}), guess["optional"])
    problems = validate(profile)
    if problems:
        for problem in problems:
            print(f"invalid: {problem}", file=sys.stderr)
        return 1

    offer_install(profile, found, args.yes, not args.no_install and not args.dry_run)
    profile["optional"][KIT_PLUGIN] = bool(found.get(KIT_PLUGIN))

    body = json.dumps(profile, indent=2) + "\n"
    if args.dry_run:
        print(body)
        return 0
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {existing}")
    missing = [s for s in needed_skills(profile) if not found.get(KIT_PLUGIN)]
    if missing:
        print(f"without {KIT_PLUGIN} these are reported as skipped: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
