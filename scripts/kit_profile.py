#!/usr/bin/env python
"""The kit's profile: the one file every skill reads.

A profile is JSON at `.claude/dotnet-workflow-kit.json` in the project (committed, shared
by the team) or at `~/.claude/dotnet-workflow-kit.json` (personal fallback). Setup writes
it; skills and the check/build scripts only read it.

    from kit_profile import resolve_profile, plan_sections
    profile = resolve_profile(Path.cwd())

Run directly to print the resolved profile:  python kit_profile.py [--profile <file>]
"""
import argparse
import json
import sys
from pathlib import Path

SCHEMA = 1
FILE_NAME = "dotnet-workflow-kit.json"

ENUMS = {
    "architecture": ("clean", "vertical", "ddd-clean", "modular-monolith"),
    "tracker": ("azure-boards", "github-issues", "jira", "none"),
    "scm": ("github", "azure-repos"),
    "testing.tdd": ("strict", "encouraged", "none"),
    "testing.unit": ("xunit", "nunit", "mstest"),
    "testing.integration": ("webapplicationfactory", "testcontainers", "none"),
    "testing.acceptance": ("reqnroll", "specflow", "none"),
    "qa.owner": ("qa-team", "self", "none"),
    "qa.evidence": ("work-item", "pr-comment", "none"),
    "stack.data": ("ef-core", "dapper", "cosmos", "other"),
    "stack.api": ("minimal-api", "controllers", "graphql", "grpc"),
    "stack.messaging": ("masstransit", "wolverine", "service-bus", "none"),
    "stack.errors": ("result", "exceptions"),
    "stack.local_run": ("aspire", "docker", "plain"),
    "stack.frontend": ("none", "blazor", "razor", "react", "angular", "vue", "javascript"),
}

BUILT_IN_REVIEWERS = ("bug-hunt", "conventions")
OPTIONAL_REVIEWERS = ("kit", "security-scan", "convention-learner", "code-review-workflow")

DEFAULTS = {
    "schema": SCHEMA,
    "user": "",
    "architecture": "clean",
    "testing": {"tdd": "encouraged", "unit": "xunit", "integration": "webapplicationfactory", "acceptance": "none"},
    "qa": {"owner": "self", "evidence": "none", "handoff_label": "", "deploy_label": "", "environment": "local"},
    "tracker": "none",
    "tracker_project": "",
    "scm": "github",
    "base_branch": "main",
    "branch_pattern": "{kind}/{id}-{slug}",
    "branch_kinds": {"feature": "feat", "bug": "bug"},
    "tracker_states": {"active": "", "qa_ready": ""},
    "artifacts": True,
    "branding": True,
    "stack": {"data": "ef-core", "api": "minimal-api", "messaging": "none", "errors": "exceptions", "local_run": "plain", "frontend": "none"},
    "reviewers": list(BUILT_IN_REVIEWERS),
    "pipeline": {"execute": "", "resolve_comments": "", "qa": ""},
    "optional": {"dotnet-claude-kit": False, "codex": False, "roslyn-mcp": False},
}

# Which dotnet-claude-kit skills an answer needs. Setup offers the install when any is missing.
NEEDS = {
    ("architecture", "clean"): ["clean-architecture"],
    ("architecture", "ddd-clean"): ["clean-architecture", "ddd"],
    ("architecture", "vertical"): ["vertical-slice"],
    ("testing.tdd", "strict"): ["tdd"],
    ("stack.data", "ef-core"): ["ef-core", "migration-workflow"],
    ("stack.api", "minimal-api"): ["minimal-api", "openapi", "api-versioning"],
    ("stack.messaging", "masstransit"): ["messaging"],
    ("stack.messaging", "wolverine"): ["messaging"],
    ("stack.errors", "result"): ["error-handling"],
    ("stack.local_run", "aspire"): ["aspire"],
    ("reviewers", "kit"): ["code-review", "80-20-review", "de-sloppify", "verification-loop"],
    ("reviewers", "security-scan"): ["security-scan"],
    ("reviewers", "convention-learner"): ["convention-learner"],
    ("reviewers", "code-review-workflow"): ["code-review-workflow"],
}
NEEDS_MCP = {"code-review-workflow": "roslyn-mcp"}

# Plan section order per architecture: (name, standard prose-word cap, max bullets).
# Clean is the exercised path; vertical is defined and marked untested in the README.
PLAN_SECTIONS = {
    "clean": [
        ("Context", 150, None), ("Requirement", 100, None), ("Specs", 40, None),
        ("Domain", 100, None), ("Application", 160, None), ("Infrastructure", 120, None), ("API", 60, None),
        ("Tests", 180, None), ("Decisions", 120, 6), ("Risks and rollout", 120, 5), ("Open questions", 180, 3),
    ],
    "vertical": [
        ("Context", 150, None), ("Requirement", 100, None), ("Specs", 40, None),
        ("Slice", 200, None), ("Persistence", 100, None), ("Integration", 100, None), ("Endpoint", 60, None),
        ("Tests", 180, None), ("Decisions", 120, 6), ("Risks and rollout", 120, 5), ("Open questions", 180, 3),
    ],
}
PLAN_SECTIONS["ddd-clean"] = PLAN_SECTIONS["clean"]
PLAN_SECTIONS["modular-monolith"] = PLAN_SECTIONS["clean"]

# Sections a plan may carry but never has to: name -> (section it follows, cap, max bullets).
# Designs holds the screens for a frontend change and is only allowed when the profile
# says the repo has a frontend.
OPTIONAL_PLAN_SECTIONS = {
    "Designs": ("Specs", 60, None),
}

# Slice names the review's Changes tables group files by.
REVIEW_SLICES = {
    "clean": ["Domain", "Application", "Infrastructure", "API", "Tests"],
    "vertical": ["Slice", "Persistence", "Integration", "Endpoint", "Tests"],
}
REVIEW_SLICES["ddd-clean"] = REVIEW_SLICES["clean"]
REVIEW_SLICES["modular-monolith"] = REVIEW_SLICES["clean"]


def get(profile, dotted):
    node = profile
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def put(profile, dotted, value):
    parts = dotted.split(".")
    node = profile
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def deep_merge(base, override):
    out = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def migrate(raw):
    """Fill defaults for anything a lower schema lacks. Returns (profile, filled_keys)."""
    merged = deep_merge(DEFAULTS, raw)
    filled = [k for k in flat_keys(DEFAULTS) if get(raw, k) is None]
    merged["schema"] = SCHEMA
    reviewers = [r for r in merged.get("reviewers", []) if r not in BUILT_IN_REVIEWERS]
    merged["reviewers"] = list(BUILT_IN_REVIEWERS) + reviewers
    return merged, filled


def flat_keys(node, prefix=""):
    keys = []
    for key, value in node.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            keys.extend(flat_keys(value, dotted + "."))
        else:
            keys.append(dotted)
    return keys


def validate(profile):
    """Return a list of problems; empty means valid."""
    problems = []
    for dotted, allowed in ENUMS.items():
        value = get(profile, dotted)
        if value not in allowed:
            problems.append(f"{dotted} must be one of {', '.join(allowed)}; got {value!r}")
    if get(profile, "qa.evidence") == "work-item" and profile.get("tracker") == "none":
        problems.append("qa.evidence cannot be work-item when tracker is none")
    for reviewer in profile.get("reviewers", []):
        if reviewer not in BUILT_IN_REVIEWERS + OPTIONAL_REVIEWERS:
            problems.append(f"reviewers: unknown reviewer {reviewer!r}")
    for built_in in BUILT_IN_REVIEWERS:
        if built_in not in profile.get("reviewers", []):
            problems.append(f"reviewers must include the built-in {built_in!r}")
    if not isinstance(profile.get("artifacts"), bool):
        problems.append("artifacts must be true or false")
    if not isinstance(profile.get("branding"), bool):
        problems.append("branding must be true or false")
    if "{slug}" not in profile.get("branch_pattern", ""):
        problems.append("branch_pattern must contain {slug}")
    kinds = profile.get("branch_kinds", {})
    if not isinstance(kinds, dict) or not kinds.get("feature") or not kinds.get("bug"):
        problems.append("branch_kinds needs non-empty feature and bug values")
    return problems


def needed_skills(profile):
    """dotnet-claude-kit skills the profile's answers rely on, in NEEDS order."""
    skills = []
    for (dotted, value), names in NEEDS.items():
        current = get(profile, dotted)
        hit = value in current if isinstance(current, list) else current == value
        if hit:
            skills.extend(n for n in names if n not in skills)
    return skills


def profile_paths(cwd):
    return [Path(cwd) / ".claude" / FILE_NAME, Path.home() / ".claude" / FILE_NAME]


def resolve_profile(cwd=None, explicit=None):
    """Load the profile: explicit path, else project file, else user file, else DEFAULTS."""
    candidates = [Path(explicit)] if explicit else profile_paths(cwd or Path.cwd())
    for path in candidates:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            profile, filled = migrate(raw)
            profile["_source"] = str(path)
            profile["_filled"] = filled
            return profile
    profile = json.loads(json.dumps(DEFAULTS))
    profile["_source"] = "defaults"
    profile["_filled"] = []
    return profile


def plan_sections(profile):
    return PLAN_SECTIONS[profile.get("architecture", "clean")]


def optional_plan_sections(profile):
    """The optional section names this profile allows a plan to carry."""
    allowed = []
    if get(profile, "stack.frontend") not in (None, "none"):
        allowed.append("Designs")
    return allowed


def disallowed_plan_sections(profile, present):
    """Optional sections the document carries that this profile does not allow, with why."""
    allowed = optional_plan_sections(profile)
    return [f"{name}: only allowed when the profile's stack.frontend is not none"
            for name in OPTIONAL_PLAN_SECTIONS if name in present and name not in allowed]


def expected_plan_sections(profile, present):
    """The section list a plan must match: the architecture's list plus any allowed
    optional section the document actually carries, each slotted after its anchor."""
    sections = list(plan_sections(profile))
    for name in optional_plan_sections(profile):
        if name not in present:
            continue
        after, cap, bullets = OPTIONAL_PLAN_SECTIONS[name]
        index = next((i for i, (n, _, _) in enumerate(sections) if n == after), len(sections) - 1)
        sections.insert(index + 1, (name, cap, bullets))
    return sections


def review_slices(profile):
    return REVIEW_SLICES[profile.get("architecture", "clean")]


def add_profile_arg(parser):
    parser.add_argument("--profile", help=f"path to a {FILE_NAME}; default: project then user file, then defaults")
    return parser


def main():
    ap = add_profile_arg(argparse.ArgumentParser(description=__doc__.splitlines()[0]))
    args = ap.parse_args()
    profile = resolve_profile(explicit=args.profile)
    problems = validate(profile)
    print(json.dumps({k: v for k, v in profile.items() if not k.startswith("_")}, indent=2))
    print(f"source: {profile['_source']}", file=sys.stderr)
    if profile["_filled"]:
        print(f"defaults filled: {', '.join(profile['_filled'])}", file=sys.stderr)
    for problem in problems:
        print(f"invalid: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
