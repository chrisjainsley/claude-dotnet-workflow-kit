#!/usr/bin/env python
"""Read a feature page's stories and work out the order the story threads run in.

Usage:
  python feature_order.py plans/<slug>/feature.md [--profile <profile.json>]
  python feature_order.py plans/<slug>/feature.md --markdown
  python feature_order.py plans/<slug>/feature.md --briefs --items items.json [--page <url>] [--inline-specs]

The Stories table (Key | Story | Depends on | Size) and the Story specs fences (one
```gherkin block per story, opening with "Feature: <key> <title>") are the input. The
default output is JSON: the waves, and per story what it branches from, when its thread
may start and how its PR stacks, following the profile's feature.stacking:

- off: a dependent story branches from base_branch once every story it needs is merged.
- base: a story with one dependency branches from that story's branch, and its PR's base
  is that branch, set by hand. It starts once the parent's review is approved.
- gh-stack: as base, but a linear chain is linked with `gh stack`. A story whose parent
  has two stacked children falls back to base, since linking retargets sibling bases.

A story with two or more dependencies always waits for all of them to merge.

--markdown prints the body of the page's Delivery order section. --briefs prints one
thread brief per story, with `items.json` mapping each key to its tracker id (or its
slug when there is no tracker). Exit 1 when the stories are malformed.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_profile import add_profile_arg, get, resolve_profile  # noqa: E402

MAX_STORIES = 12
MAX_STORY_SCENARIOS = 4
SIZES = ("small", "standard", "large")
KEY_RE = re.compile(r"^S\d{1,2}$")
NONE_DEPS = {"", "-", "none", "n/a"}
STORIES_SECTION = "Stories"
SPECS_SECTION = "Story specs"
COLUMNS = ("key", "story", "depends on", "size")


def split_front_matter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[end + 4:]


def sections(body):
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    found, current = {}, None
    for line in body.splitlines():
        match = re.match(r"^## (.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return {name: "\n".join(lines) for name, lines in found.items()}


def table(text):
    rows = [line for line in text.splitlines() if line.lstrip().startswith("|")]
    cells = [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows]
    return [row for row in cells if not all(re.fullmatch(r":?-{2,}:?", c) for c in row)]


def parse_stories(text):
    """Return (stories, problems). Each story is {key, title, depends, size}."""
    rows = table(text)
    if not rows:
        return [], [f"{STORIES_SECTION}: no table found"]
    header = [c.lower() for c in rows[0]]
    if tuple(header) != COLUMNS:
        return [], [f"{STORIES_SECTION}: columns must be exactly Key | Story | Depends on | Size; got {' | '.join(rows[0])}"]
    stories, problems = [], []
    for row in rows[1:]:
        if len(row) != len(COLUMNS):
            problems.append(f"{STORIES_SECTION}: row has {len(row)} cells, expected {len(COLUMNS)}: {' | '.join(row)}")
            continue
        key, title, depends, size = row
        deps = [] if depends.lower() in NONE_DEPS else [d.strip() for d in depends.split(",") if d.strip()]
        stories.append({"key": key, "title": title, "depends": deps, "size": size.lower()})
    return stories, problems


def parse_specs(text):
    """Map each story key to its Gherkin block from the Story specs fences."""
    specs = {}
    for block in re.findall(r"```gherkin\s*\n(.*?)```", text, flags=re.S):
        first = next((line.strip() for line in block.splitlines() if line.strip()), "")
        match = re.match(r"^Feature:\s*(S\d{1,2})\b", first)
        key = match.group(1) if match else ""
        specs.setdefault(key, []).append(block.rstrip())
    return specs


def validate(stories, specs):
    problems = []
    keys = [s["key"] for s in stories]
    if not stories:
        problems.append(f"{STORIES_SECTION}: no stories")
    if len(stories) > MAX_STORIES:
        problems.append(f"{STORIES_SECTION}: {len(stories)} stories, cap {MAX_STORIES}; split the feature")
    for story in stories:
        key = story["key"]
        if not KEY_RE.match(key):
            problems.append(f"{STORIES_SECTION}: key {key!r} must look like S1, S2")
        if keys.count(key) > 1:
            problems.append(f"{STORIES_SECTION}: duplicate key {key}")
        if not story["title"]:
            problems.append(f"{STORIES_SECTION}: {key} has no story text")
        if story["size"] not in SIZES:
            problems.append(f"{STORIES_SECTION}: {key} size must be one of {', '.join(SIZES)}; got {story['size']!r}")
        for dep in story["depends"]:
            if dep == key:
                problems.append(f"{STORIES_SECTION}: {key} depends on itself")
            elif dep not in keys:
                problems.append(f"{STORIES_SECTION}: {key} depends on unknown story {dep}")
        blocks = specs.get(key, [])
        if not blocks:
            problems.append(f"{SPECS_SECTION}: no ```gherkin block opening with 'Feature: {key}'")
        scenarios = sum(len(re.findall(r"^\s*Scenario(?: Outline)?:", b, flags=re.M)) for b in blocks)
        if blocks and scenarios == 0:
            problems.append(f"{SPECS_SECTION}: {key} has no scenario")
        if scenarios > MAX_STORY_SCENARIOS:
            problems.append(f"{SPECS_SECTION}: {key} has {scenarios} scenarios, cap {MAX_STORY_SCENARIOS}")
    for key in specs:
        if key not in keys:
            problems.append(f"{SPECS_SECTION}: a block names {key or 'no story'}; open each with 'Feature: <key> <title>'")
    if not problems and waves(stories) is None:
        problems.append(f"{STORIES_SECTION}: the dependencies form a cycle")
    return problems


def waves(stories):
    """Stories grouped by dependency depth, in table order within a wave; None on a cycle."""
    remaining = {s["key"]: set(s["depends"]) for s in stories}
    done, out = set(), []
    while remaining:
        ready = [s["key"] for s in stories if s["key"] in remaining and remaining[s["key"]] <= done]
        if not ready:
            return None
        out.append(ready)
        done.update(ready)
        for key in ready:
            del remaining[key]
    return out


def delivery(stories, stacking, base_branch):
    """Per story: what it branches from, when it may start and how its PR stacks."""
    by_key = {s["key"]: s for s in stories}
    stacked_children = {}
    if stacking != "off":
        for story in stories:
            if len(story["depends"]) == 1:
                stacked_children.setdefault(story["depends"][0], []).append(story["key"])

    def linear(key):
        """True when every story from the chain's root down to this one has one parent
        and that parent has no other stacked child: the shape `gh stack` can hold."""
        story = by_key[key]
        while story["depends"]:
            if len(story["depends"]) != 1:
                return False
            parent = story["depends"][0]
            if len(stacked_children.get(parent, [])) != 1:
                return False
            story = by_key[parent]
        return True

    plan = []
    for story in stories:
        deps = story["depends"]
        entry = {"key": story["key"], "title": story["title"], "size": story["size"], "depends": deps,
                 "base": base_branch, "base_story": None, "start": "now", "stack": "none"}
        if len(deps) == 1 and stacking != "off":
            entry.update(base=None, base_story=deps[0], start="approved",
                         stack="gh-stack" if stacking == "gh-stack" and linear(story["key"]) else "base")
        elif deps:
            entry["start"] = "merged"
        plan.append(entry)
    return plan


def load(path, profile):
    meta, body = split_front_matter(Path(path).read_text(encoding="utf-8"))
    found = sections(body)
    stories, problems = parse_stories(found.get(STORIES_SECTION, ""))
    specs = parse_specs(found.get(SPECS_SECTION, ""))
    problems += validate(stories, specs) if not problems else []
    stacking = get(profile, "feature.stacking") or "base"
    base_branch = meta.get("base") or profile.get("base_branch", "main")
    result = {"title": meta.get("title", ""), "ticket": meta.get("ticket", ""), "base_branch": base_branch,
              "stacking": stacking, "waves": [], "stories": []}
    if not problems:
        result["waves"] = waves(stories)
        result["stories"] = delivery(stories, stacking, base_branch)
        for entry in result["stories"]:
            entry["specs"] = specs.get(entry["key"], [])
    return result, problems


def start_text(entry):
    deps = ", ".join(entry["depends"])
    if entry["start"] == "now":
        return "now"
    if entry["start"] == "approved":
        return f"once {deps}'s review is approved and its pull request is ready"
    return f"once {deps} {'is' if len(entry['depends']) == 1 else 'are'} merged"


def base_text(entry, items=None):
    if entry["base_story"] is None:
        return f"`{entry['base']}`"
    parent = entry["base_story"]
    ident = f" ({items[parent]})" if items and parent in items else ""
    how = "linked with `gh stack`" if entry["stack"] == "gh-stack" else "PR base set by hand"
    return f"the branch of {parent}{ident}, stacked ({how})"


def markdown(result):
    lines = []
    for index, wave in enumerate(result["waves"], start=1):
        lines.append(f"{index}. Wave {index}: {', '.join(wave)}.")
    lines.append("")
    lines.append("| Story | Branches from | Starts |")
    lines.append("|---|---|---|")
    for entry in result["stories"]:
        lines.append(f"| {entry['key']} | {base_text(entry)} | {start_text(entry)} |")
    lines.append("")
    lines.append(f"Stacking: `{result['stacking']}`.")
    return "\n".join(lines)


def briefs(result, items, page="", inline_specs=False):
    out = []
    total = len(result["stories"])
    for entry in result["stories"]:
        ident = items.get(entry["key"])
        if not ident:
            raise KeyError(f"items.json has no id for {entry['key']}")
        where = f" on the feature page: {page}" if page else ""
        lines = [
            f"/dotnet-workflow-kit:next {ident}",
            "",
            f"Feature story {entry['key']} of {total} in \"{result['title']}\", approved{where}.",
            f"Branch from {base_text(entry, items)}.",
            f"Start {start_text(entry)}.",
        ]
        if inline_specs and entry["specs"]:
            lines += ["", entry["title"], "", "```gherkin", *[s for s in entry["specs"]], "```"]
        out.append(f"### {entry['key']} {entry['title']}\n\n````text\n" + "\n".join(lines) + "\n````")
    return "\n\n".join(out)


def main(argv=None):
    ap = add_profile_arg(argparse.ArgumentParser(description=__doc__.splitlines()[0]))
    ap.add_argument("source")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--markdown", action="store_true", help="print the Delivery order section body")
    mode.add_argument("--briefs", action="store_true", help="print one thread brief per story")
    ap.add_argument("--items", help="with --briefs: JSON file mapping each story key to its tracker id or slug")
    ap.add_argument("--page", default="", help="with --briefs: the approved feature page's URL")
    ap.add_argument("--inline-specs", action="store_true", help="with --briefs: carry each story's specs in its brief (tracker none)")
    args = ap.parse_args(argv)
    profile = resolve_profile(explicit=args.profile)
    result, problems = load(args.source, profile)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    if args.markdown:
        print(markdown(result))
    elif args.briefs:
        if not args.items:
            print("--briefs needs --items", file=sys.stderr)
            return 1
        items = json.loads(Path(args.items).read_text(encoding="utf-8"))
        try:
            print(briefs(result, items, args.page, args.inline_specs))
        except KeyError as error:
            print(error.args[0], file=sys.stderr)
            return 1
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
