#!/usr/bin/env python
"""Fail loudly when a plan.md breaks the section skeleton or its word budget.

Usage: python check_plan.py plans/<slug>/plan.md [--profile <dotnet-workflow-kit.json>]

The section list and caps come from the profile's architecture (scripts/profile.py).

Exit 0 when every check passes, 1 otherwise. Prints one table so the author sees
every breach at once instead of fixing them one run at a time.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from profile import add_profile_arg, plan_sections, resolve_profile  # noqa: E402

SECTIONS = plan_sections(resolve_profile())  # replaced in main() when --profile is given
SIZE_MULTIPLIER = {"small": 0.6, "standard": 1.0, "large": 1.5}
MAX_SCENARIOS = 6
BANNED = [
    (re.compile("—"), "em dash"),
    (re.compile(r"\bsettled on\b", re.I), "'Settled on' recap"),
    (re.compile(r"\bas discussed\b", re.I), "'as discussed' (plan must stand alone)"),
    (re.compile(r"\bthis revision\b|\bprevious (plan|draft|version)\b|\bprior (plan|draft|version)\b", re.I),
     "revision language (plan must stand alone)"),
    (re.compile(r"\breuse first\b|\bwhat it reuses\b", re.I), "reuse-before-add ritual"),
    (re.compile(r"\bnot built\b|\bnot used\b\.", re.I), "rejected-option narration"),
]


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


def split_sections(body):
    sections = []
    current = None
    for line in body.splitlines():
        match = re.match(r"^## (.+?)\s*$", line)
        if match:
            current = [match.group(1).strip(), []]
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return [(name, "\n".join(lines)) for name, lines in sections]


def strip_fences(text):
    prose, code, in_fence = [], [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        (code if in_fence else prose).append(line)
    return "\n".join(prose), "\n".join(code)


def count_words(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "code", text)
    text = re.sub(r"^\s*[-*]\s+\[[xX ]\]", "-", text, flags=re.M)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\]\((https?://|[A-Za-z0-9_./-]+\.(png|jpe?g|gif|webp))[^)]*\)", "]", text)
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'./#:_-]*", text))


def count_bullets(text):
    return len(re.findall(r"^(?:[-*]|\d+\.)\s+", text, flags=re.M))


def main(path, profile=None):
    global SECTIONS
    if profile is not None:
        SECTIONS = plan_sections(profile)
    text = Path(path).read_text(encoding="utf-8")
    meta, body = split_front_matter(text)
    size = meta.get("size", "standard")
    if size not in SIZE_MULTIPLIER:
        print(f"size must be one of {sorted(SIZE_MULTIPLIER)}, got '{size}'")
        return 1
    multiplier = SIZE_MULTIPLIER[size]
    failures = []
    for key in ("title", "ticket"):
        if not meta.get(key):
            failures.append(f"front matter is missing '{key}'")

    found = split_sections(body)
    found_names = [name for name, _ in found]
    expected_names = [name for name, _, _ in SECTIONS]
    if found_names != expected_names:
        failures.append("sections must be exactly, in order: " + " > ".join(expected_names))
        failures.append("found: " + " > ".join(found_names))

    rows = []
    total_prose = 0
    by_name = dict(found)
    for name, cap, max_bullets in SECTIONS:
        content = by_name.get(name, "")
        prose, code = strip_fences(content)
        words = count_words(prose)
        total_prose += words
        limit = round(cap * multiplier)
        bullets = count_bullets(prose)
        status = "ok"
        if words > limit:
            status = "OVER"
            failures.append(f"{name}: {words} prose words, cap {limit}")
        if max_bullets is not None and bullets > max_bullets:
            status = "OVER"
            failures.append(f"{name}: {bullets} items, cap {max_bullets}")
        if name == "Specs":
            scenarios = len(re.findall(r"^\s*Scenario(?: Outline)?:", code, flags=re.M))
            if scenarios == 0:
                failures.append("Specs: no Gherkin scenario found in a fenced block")
            if scenarios > MAX_SCENARIOS:
                failures.append(f"Specs: {scenarios} scenarios, cap {MAX_SCENARIOS}")
        if name == "Open questions":
            for question in re.split(r"^\d+\.\s", prose, flags=re.M)[1:]:
                options = re.findall(r"^\s+[-*]\s+\[([xX ])\]", question, flags=re.M)
                if options and sum(1 for o in options if o.lower() == "x") != 1:
                    failures.append("Open questions: each question with options needs exactly one [x] recommended option")
        if not content.strip():
            failures.append(f"{name}: empty. Write 'No change.' if the layer is untouched")
        rows.append((name, words, limit, bullets, status))

    prose_only, _ = strip_fences(body)
    for pattern, label in BANNED:
        for match in pattern.finditer(prose_only):
            line_no = prose_only.count("\n", 0, match.start()) + 1
            failures.append(f"banned: {label} (prose line {line_no})")

    print(f"{'section':<20}{'words':>7}{'cap':>6}{'items':>7}  status")
    for name, words, limit, bullets, status in rows:
        print(f"{name:<20}{words:>7}{limit:>6}{bullets:>7}  {status}")
    print(f"{'total prose':<20}{total_prose:>7}{round(sum(c for _, c, _ in SECTIONS) * multiplier):>6}")
    if failures:
        print("\nFAILED")
        for failure in failures:
            print(" - " + failure)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    import argparse
    ap = add_profile_arg(argparse.ArgumentParser(description=__doc__.splitlines()[0]))
    ap.add_argument("source")
    args = ap.parse_args()
    sys.exit(main(args.source, resolve_profile(explicit=args.profile)))
