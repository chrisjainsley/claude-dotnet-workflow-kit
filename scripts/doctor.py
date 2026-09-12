#!/usr/bin/env python
"""Check that the kit will work for the resolved profile, and say what will run.

    python doctor.py [--profile <file>] [--skip-fixtures]

Reports: where the profile came from and whether it validates; the adapter file each
profile value resolves to; which mega-review reviewers will run and which will be skipped
and why; and, unless --skip-fixtures, that the plan and review checkers still pass on the
shipped fixtures. Exit 1 on any problem. Needs only Python; never calls the claude CLI.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile import (  # noqa: E402
    BUILT_IN_REVIEWERS, ENUMS, NEEDS, NEEDS_MCP, add_profile_arg, get, resolve_profile, validate,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
FIXTURES = ROOT / "tests" / "fixtures"
KIT = "dotnet-claude-kit"
FOLDER_CONCERNS = {"tracker": "tracker", "scm": "scm", "architecture": "architecture", "qa.owner": "qa"}


def adapter_path(concern, value):
    """Return the adapter file for a concern value, or None. Folder adapters hold a README.md."""
    flat = ADAPTERS / concern / f"{value}.md"
    folder = ADAPTERS / concern / value / "README.md"
    return flat if flat.exists() else folder if folder.exists() else None


def stack_section(field, value):
    """Stack adapters are one file per field with a ## heading per value."""
    path = ADAPTERS / "stack" / f"{field}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return path if re.search(rf"^## {re.escape(value)}\s*$", text, flags=re.M) else None


def adapter_report(profile):
    rows, problems = [], []
    for dotted, folder in FOLDER_CONCERNS.items():
        value = get(profile, dotted)
        path = adapter_path(folder, value)
        rows.append((dotted, value, path))
        if path is None:
            problems.append(f"no adapter for {dotted}={value!r} under adapters/{folder}/")
    for dotted in ENUMS:
        if not dotted.startswith("stack."):
            continue
        field, value = dotted.split(".", 1)[1], get(profile, dotted)
        path = stack_section(field, value)
        rows.append((dotted, value, path))
        if path is None:
            problems.append(f"adapters/stack/{field}.md has no '## {value}' section")
    return rows, problems


def reviewer_report(profile):
    """(name, status, reason) for every reviewer the profile enables."""
    optional = profile.get("optional", {})
    rows = []
    for name in profile.get("reviewers", []):
        if name in BUILT_IN_REVIEWERS:
            rows.append((name, "runs", "built in"))
            continue
        needs = NEEDS.get(("reviewers", name), [])
        if not optional.get(KIT):
            rows.append((name, "skipped", f"{KIT} not installed; needs {', '.join(needs)}"))
        elif name in NEEDS_MCP and not optional.get(NEEDS_MCP[name]):
            rows.append((name, "skipped", f"needs the {NEEDS_MCP[name]} server"))
        else:
            rows.append((name, "runs", ", ".join(needs)))
    if optional.get("codex"):
        rows.append(("codex", "runs", "second opinion via codex:rescue"))
    return rows


def fixture_report():
    """Run the shared checker on both fixtures; (kind, ok, last line)."""
    checker = ROOT / "scripts" / "check.py"
    results = []
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for kind in ("plan", "review"):
        fixture = FIXTURES / f"{kind}.md"
        if not checker.exists() or not fixture.exists():
            results.append((kind, None, "checker or fixture missing"))
            continue
        run = subprocess.run([sys.executable, str(checker), str(fixture), "--kind", kind],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        last = (run.stdout.strip().splitlines() or [run.stderr.strip()[-120:]])[-1]
        results.append((kind, run.returncode == 0, last))
    return results


def main(argv=None):
    ap = add_profile_arg(argparse.ArgumentParser(description=__doc__.splitlines()[0]))
    ap.add_argument("--skip-fixtures", action="store_true")
    args = ap.parse_args(argv)
    profile = resolve_profile(explicit=args.profile)
    problems = validate(profile)

    print(f"profile: {profile['_source']}")
    if profile["_filled"]:
        print(f"  defaults filled: {', '.join(profile['_filled'])}")
    for problem in problems:
        print(f"  invalid: {problem}")

    print("adapters:")
    rows, adapter_problems = adapter_report(profile)
    for dotted, value, path in rows:
        shown = path.relative_to(ROOT).as_posix() if path else "MISSING"
        print(f"  {dotted:<18} {str(value):<22} {shown}")
    problems += adapter_problems

    print("reviewers:")
    for name, status, reason in reviewer_report(profile):
        print(f"  {name:<22} {status:<8} {reason}")

    if not args.skip_fixtures:
        print("fixtures:")
        for kind, ok, line in fixture_report():
            state = "ok" if ok else "FAIL" if ok is False else "skipped"
            print(f"  {kind:<8} {state:<8} {line}")
            if ok is False:
                problems.append(f"{kind} fixture fails the checker")

    print("result: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
