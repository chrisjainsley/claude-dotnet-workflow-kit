#!/usr/bin/env python
"""Fail loudly when a plan.md or review.md breaks its section skeleton or word budget.

Usage:
  python check.py plans/<slug>/plan.md [--profile <profile.json>]
  python check.py plans/<slug>/review.md

`--kind plan|review` picks the rule set; without it the kind is inferred from the
## section names, then from the front matter. Plan sections and caps come from the
profile's architecture (scripts/kit_profile.py); review sections are the same for every
architecture, and --profile is accepted there so the command lines match.

Exit 0 when every check passes, 1 otherwise. Prints one table so the author sees
every breach at once instead of fixing them one run at a time.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_profile import (  # noqa: E402
    add_profile_arg, disallowed_plan_sections, expected_plan_sections, resolve_profile, review_slices,
)
import flowmap  # noqa: E402

SIZE_MULTIPLIER = {"small": 0.6, "standard": 1.0, "large": 1.5}

MAX_SCENARIOS = 6
PLAN_BANNED = [
    (re.compile("—"), "em dash"),
    (re.compile(r"\bsettled on\b", re.I), "'Settled on' recap"),
    (re.compile(r"\bas discussed\b", re.I), "'as discussed' (plan must stand alone)"),
    (re.compile(r"\bthis revision\b|\bprevious (plan|draft|version)\b|\bprior (plan|draft|version)\b", re.I),
     "revision language (plan must stand alone)"),
    (re.compile(r"\breuse first\b|\bwhat it reuses\b", re.I), "reuse-before-add ritual"),
    (re.compile(r"\bnot built\b|\bnot used\b\.", re.I), "rejected-option narration"),
]

REVIEW_SECTIONS = [
    # name, standard prose-word cap
    ("Verdict", 80),
    ("Plan versus delivered", 160),
    ("Changes", 300),
    ("Contracts and coordination", 140),
    ("Findings", 200),
    ("QA report", 350),
    ("Rollout", 90),
    ("Decision", 60),
]
MAX_HUNKS = 8
MAX_HUNK_LINES = 60
MAX_ROLLOUT_ITEMS = 8
REVIEW_BANNED = [
    (re.compile("—"), "em dash"),
    (re.compile(r"\bas discussed\b", re.I), "'as discussed' (review must stand alone)"),
    (re.compile(r"\bthis revision\b|\bprevious (plan|draft|version)\b", re.I), "revision language"),
    (re.compile(r"\brobust\b|\bseamless(ly)?\b|\bleverag(e|es|ing)\b", re.I), "filler adjective"),
]
REVIEW_META = ("title", "ticket", "pr", "branch", "base")
# The optional narrated walkthrough: numbered scenes after Decision, each a backticked
# target (a section, "Section > text" for a row or heading in it, or "@node" for a
# flowmap box) and one spoken line. The page reads it aloud with the browser's own voice.
WALKTHROUGH = "Walkthrough"
WALKTHROUGH_CAP = 220
MAX_SCENES = 8
MAX_SCENE_WORDS = 45
SCENE_RE = re.compile(r"^\s*\d+\.\s+`([^`]+)`\s+(.+?)\s*$")
SPOKEN_BANNED = [
    (re.compile(r"[`*_\[\]<>|]"), "markdown or markup (the line is read aloud)"),
    (re.compile(r"https?://"), "a URL (the line is read aloud)"),
    (re.compile(r"\d\s*/\s*\d"), "a slash count like 10/11 (write 'ten of eleven')"),
]


def walkthrough_scenes(text):
    """([(target, narration)], [stray lines]) from the Walkthrough section body."""
    scenes, stray = [], []
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        if not line.strip():
            continue
        m = SCENE_RE.match(line)
        if m:
            scenes.append((m.group(1).strip(), m.group(2).strip()))
        elif scenes and line.startswith("   "):
            scenes[-1] = (scenes[-1][0], scenes[-1][1] + " " + line.strip())
        else:
            stray.append(line.strip())
    return scenes, stray


def scene_target(target):
    """('node', id, None) for '@id', else ('section', name, needle or None)."""
    if target.startswith("@"):
        return "node", target[1:].strip(), None
    name, _, needle = target.partition(">")
    return "section", name.strip(), needle.strip() or None


def check_walkthrough(text, by_name, multiplier):
    """Scene count, words per scene and in total, spoken-text hygiene, and that every
    target names a review section, text inside it, or a flowmap node."""
    failures = []
    scenes, stray = walkthrough_scenes(text)
    for line in stray:
        failures.append(f"Walkthrough: '{line[:40]}' is not a scene; write '1. `Section` spoken line'")
    if not scenes:
        failures.append("Walkthrough: no scenes; drop the section or add '1. `Verdict` spoken line'")
    if len(scenes) > MAX_SCENES:
        failures.append(f"Walkthrough: {len(scenes)} scenes, cap {MAX_SCENES}")
    maps = [b for lang, b in fences(by_name.get("Changes", "")) if lang == "flowmap"]
    nodes = {n["id"] for n in flowmap.parse("\n".join(maps[0]))[0]["nodes"]} if maps else set()
    sections = {name for name, _ in REVIEW_SECTIONS}
    total = 0
    for n, (target, words_text) in enumerate(scenes, start=1):
        kind, name, needle = scene_target(target)
        if kind == "node" and name not in nodes:
            failures.append(f"Walkthrough: scene {n} targets @{name}, which is not a flowmap node")
        elif kind == "section" and name not in sections:
            failures.append(f"Walkthrough: scene {n} targets '{name}', which is not a review section")
        elif needle and needle.lower() not in by_name.get(name, "").lower():
            failures.append(f"Walkthrough: scene {n} looks for '{needle}' in {name}, which does not contain it")
        words = count_words(words_text)
        total += words
        if words > MAX_SCENE_WORDS:
            failures.append(f"Walkthrough: scene {n} is {words} words, cap {MAX_SCENE_WORDS}")
        for pattern, label in SPOKEN_BANNED:
            if pattern.search(words_text):
                failures.append(f"Walkthrough: scene {n} has {label}")
    limit = round(WALKTHROUGH_CAP * multiplier)
    if total > limit:
        failures.append(f"Walkthrough: {total} spoken words, cap {limit}")
    return failures, total, limit


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
    sections, current = [], None
    for line in body.splitlines():
        match = re.match(r"^## (.+?)\s*$", line)
        if match:
            current = [match.group(1).strip(), []]
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return [(name, "\n".join(lines)) for name, lines in sections]


def fences(text):
    """[(lang, lines)]. The info string's first word is the language; the rest is a
    caption (QA evidence names its step there) and is ignored here."""
    blocks, current, lang = [], None, None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if current is None:
                info = line.strip()[3:].strip().split(None, 1)
                lang = info[0].lower() if info else ""
                current = []
            else:
                blocks.append((lang, current))
                current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


def captioned_fences(text):
    """[(lang, caption, body, line)] for every fence, keeping the caption after the
    language; line is the 0-based index of the opening fence."""
    blocks, current = [], None
    for n, line in enumerate(text.splitlines()):
        if line.strip().startswith("```"):
            if current is None:
                info = line.strip()[3:].strip().split(None, 1)
                current = [info[0].lower() if info else "", info[1].strip() if len(info) > 1 else "", [], n]
            else:
                blocks.append((current[0], current[1], "\n".join(current[2]), current[3]))
                current = None
            continue
        if current is not None:
            current[2].append(line)
    return blocks


def check_changes_diagram(changes, slices):
    """The Changes section opens with one diagram before the first ### service heading: a
    ```flowmap layer map (preferred) or, in older reviews, a ```mermaid flowchart. Example
    fences attach to flowmap nodes by an @id caption and sit before the first ### too."""
    failures = []
    lines = changes.splitlines()
    first_service = next((n for n, line in enumerate(lines) if line.startswith("### ")), len(lines))
    blocks = captioned_fences(changes)
    diagrams = [(lang, at) for lang, _, _, at in blocks if lang in ("flowmap", "mermaid")]
    maps = [b for lang, _, b, _ in blocks if lang == "flowmap"]
    if len(diagrams) != 1:
        found = ", ".join(f"{sum(1 for lang, _ in diagrams if lang == k)} {k}" for k in ("flowmap", "mermaid"))
        failures.append(f"Changes: needs exactly one ```flowmap layer map of the change before the first ### service heading, found {found}")
        return failures
    if diagrams[0][1] > first_service:
        failures.append("Changes: the diagram belongs before the first ### service heading")
    examples = [(lang, caption, body) for lang, caption, body, at in blocks if flowmap.example_target(caption)]
    if examples and not maps:
        failures.append("Changes: @id example fences need a ```flowmap to attach to")
    for lang, caption, _, at in blocks:
        if flowmap.example_target(caption) and at > first_service:
            failures.append(f"Changes: example '{caption[:40]}' belongs before the first ### service heading")
    if maps:
        spec, errors = flowmap.parse(maps[0])
        errors += flowmap.validate(spec, slices)
        errors += flowmap.validate_examples(examples, spec)
        failures += ["Changes: flowmap " + e for e in errors]
    return failures


def step_key(text):
    """Normalise a gherkin step or an evidence caption for matching: case and spacing."""
    return re.sub(r"\s+", " ", text.strip().rstrip(".:")).lower()


STEP_RE = re.compile(r"^\s*(Given|When|Then|And|But|\*)(?=\s)", re.I)
IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
REDACTED = "<redacted>"
# A credential-bearing key anywhere on a line (header, curl -H, JSON, query string,
# connection string): the key must end with the credential word, so passwordReset or
# token_type do not count. The value after it must be <redacted> or a JSON literal, and
# <redacted> must be the whole value: "<redacted>abc" still leaks abc.
VALUE_END = r"(?:[\"',;&}\s]|$)"
CREDENTIAL_KEY_RE = re.compile(
    r"\b[\w-]*(password|passwd|pwd|secret|token|api[-_]?key)[\"']?\s*[:=]\s*[\"']?"
    rf"(?!<redacted>{VALUE_END}|null\b|true\b|false\b|[\"',}}\s]|$)", re.I | re.M)
AUTH_RE = re.compile(rf"\b(proxy-)?authorization[\"']?\s*:\s*(?![\"']?(\w+\s+)?<redacted>{VALUE_END})\S", re.I | re.M)
COOKIE_RE = re.compile(r"\b(set-)?cookie[\"']?\s*:\s*[\"']?([^\"'\n]*)", re.I)
# A custom header whose name carries a credential (X-Api-Token, X-Hub-Signature,
# Ocp-Apim-Subscription-Key): the whole header value must be <redacted>.
CUSTOM_HEADER_RE = re.compile(
    r"(?:^\s*|-H\s+[\"'])([\w-]*(?:token|key|secret|signature)[\w-]*)\s*:\s*"
    rf"(?!<redacted>{VALUE_END})(?=\S)", re.I | re.M)
MAX_EVIDENCE_IMAGES = 10
MAX_EVIDENCE_VIDEOS = 3
VIDEO_EXTENSIONS = (".webm", ".mp4", ".mov")
MAX_MEDIA_FILE_BYTES = 15 * 1024 * 1024
MAX_MEDIA_TOTAL_BYTES = 60 * 1024 * 1024
SOURCE_DIR = Path(".")


def is_video(path):
    return path.lower().endswith(VIDEO_EXTENSIONS)


def credential_leaks(text):
    """Kinds of credential left unredacted in an evidence block."""
    leaks = []
    if AUTH_RE.search(text):
        leaks.append("Authorization header")
    for m in COOKIE_RE.finditer(text):
        pairs = [p for p in m.group(2).split(";") if p.strip()]
        # Set-Cookie carries attributes (Path=/, HttpOnly) after its one value.
        pairs = pairs[:1] if m.group(1) else pairs
        if any(p.split("=", 1)[-1].strip() != REDACTED for p in pairs):
            leaks.append("cookie")
            break
    for m in CREDENTIAL_KEY_RE.finditer(text):
        word = m.group(1).lower()
        leaks.append("API key" if word.startswith("api") else "password" if word.startswith("p") else word)
    for m in CUSTOM_HEADER_RE.finditer(text):
        if not CREDENTIAL_KEY_RE.match(text, m.start(1)):
            leaks.append(f"{m.group(1)} header")
    return list(dict.fromkeys(leaks))


def qa_scenarios(qa):
    """[(title, text)] per '#### ' scenario block in the QA report, split outside fences."""
    scenarios, in_fence = [], False
    for line in qa.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if line.startswith("#### ") and not in_fence:
            scenarios.append([line[5:].strip(), []])
        elif scenarios:
            scenarios[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in scenarios]


def evidence_items(block):
    """(gherkin lines, [(kind, caption, lines)]) for one scenario. Evidence is what the
    page folds into steps: unindented fences and image lines after the gherkin fence."""
    lines, gherkin, items, i = block.splitlines(), None, [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            info = line[3:].strip().split(None, 1)
            lang = info[0].lower() if info else ""
            body, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            if lang in ("gherkin", "feature") and gherkin is None:
                gherkin = body
            elif gherkin is not None:
                items.append((lang, info[1].strip() if len(info) > 1 else "", body))
        elif gherkin is not None and IMAGE_LINE_RE.match(line.strip()):
            cap, path = IMAGE_LINE_RE.match(line.strip()).groups()
            items.append(("video" if is_video(path) else "image", cap, [path]))
        i += 1
    return gherkin or [], items


def check_evidence(qa, multiplier):
    """Evidence under each scenario: every fence, image or video names a step of that
    scenario's gherkin (or the scenario title, for whole-run media), no credential is left
    unredacted, every media file exists within the artifact's file limits, and images and
    videos stay under their caps."""
    failures, images, videos, total, seen = [], 0, 0, 0, set()
    for title, block in qa_scenarios(qa):
        name = re.sub(r"\s*`.*$", "", title)
        gherkin, items = evidence_items(block)
        steps = {step_key(l) for l in gherkin if STEP_RE.match(l)} | {step_key(name)}
        for lang, cap, body in items:
            if lang in ("image", "video"):
                images += lang == "image"
                videos += lang == "video"
                path, file = body[0], SOURCE_DIR / body[0]
                if not file.is_file():
                    failures.append(f"QA report: evidence file {path} under '{name}' does not exist next to the review")
                elif path not in seen:
                    seen.add(path)
                    size = file.stat().st_size
                    total += size
                    if size > MAX_MEDIA_FILE_BYTES:
                        failures.append(f"QA report: {path} is {size / 1048576:.1f} MB, cap 15 MB per file; trim or re-encode it")
            if step_key(cap) not in steps:
                label = f"'{cap}'" if cap else f"an uncaptioned {lang} block"
                failures.append(f"QA report: {label} under '{name}' names no step of its gherkin; caption it with the step it proves")
        # Every fence in the scenario is scanned, evidence or not: a leak is a leak.
        for lang, body in fences(block):
            if lang not in ("gherkin", "feature"):
                for what in credential_leaks("\n".join(body)):
                    failures.append(f"QA report: unredacted {what} in evidence under '{name}'; replace the value with <redacted>")
    cap = round(MAX_EVIDENCE_IMAGES * multiplier)
    if images > cap:
        failures.append(f"QA report: {images} evidence images, cap {cap}")
    video_cap = round(MAX_EVIDENCE_VIDEOS * multiplier)
    if videos > video_cap:
        failures.append(f"QA report: {videos} evidence videos, cap {video_cap}")
    if total > MAX_MEDIA_TOTAL_BYTES:
        failures.append(f"QA report: evidence files total {total / 1048576:.1f} MB, cap 60 MB")
    return failures, images, videos


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


def table_rows(text):
    rows = [l for l in text.splitlines() if l.lstrip().startswith("|")]
    return [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows
            if not re.fullmatch(r"\|(\s*:?-{2,}:?\s*\|)+", r.strip())]


def infer_kind(meta, section_names):
    names = set(section_names)
    if names & {"Verdict", "Changes", "Findings", "Decision", "QA report", "Rollout"}:
        return "review"
    if names & {"Requirement", "Open questions", "Context", "Specs"}:
        return "plan"
    declared = meta.get("kind", "").strip().lower()
    if declared in ("plan", "review"):
        return declared
    if meta.get("pr") or meta.get("state"):
        return "review"
    return "plan"


def report_banned(body, banned, failures, strip_code=False):
    prose_only, _ = strip_fences(body)
    if strip_code:
        prose_only = re.sub(r"`[^`]*`", "", prose_only)
    for pattern, label in banned:
        for match in pattern.finditer(prose_only):
            line_no = prose_only.count("\n", 0, match.start()) + 1
            failures.append(f"banned: {label} (prose line {line_no})")


def report(failures):
    if failures:
        print("\nFAILED")
        for failure in failures:
            print(" - " + failure)
        return 1
    print("\nOK")
    return 0


def check_plan(meta, body, multiplier, sections, disallowed=()):
    failures = list(disallowed)
    for key in ("title", "ticket"):
        if not meta.get(key):
            failures.append(f"front matter is missing '{key}'")

    found = split_sections(body)
    found_names = [name for name, _ in found]
    expected_names = [name for name, _, _ in sections]
    if found_names != expected_names:
        failures.append("sections must be exactly, in order: " + " > ".join(expected_names))
        failures.append("found: " + " > ".join(found_names))

    rows, total_prose = [], 0
    by_name = dict(found)
    for name, cap, max_bullets in sections:
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

    report_banned(body, PLAN_BANNED, failures)

    print(f"{'section':<20}{'words':>7}{'cap':>6}{'items':>7}  status")
    for name, words, limit, bullets, status in rows:
        print(f"{name:<20}{words:>7}{limit:>6}{bullets:>7}  {status}")
    print(f"{'total prose':<20}{total_prose:>7}{round(sum(c for _, c, _ in sections) * multiplier):>6}")
    return report(failures)


def check_review(meta, body, multiplier, slices=None):
    failures = [f"front matter is missing '{k}'" for k in REVIEW_META if not meta.get(k)]

    found = split_sections(body)
    names = [n for n, _ in found]
    expected = [n for n, _ in REVIEW_SECTIONS]
    if names not in (expected, expected + [WALKTHROUGH]):
        failures.append("sections must be exactly, in order: " + " > ".join(expected)
                        + f" (then an optional {WALKTHROUGH})")
        failures.append("found: " + " > ".join(names))
    by_name = dict(found)

    rows, total = [], 0
    for name, cap in REVIEW_SECTIONS:
        content = by_name.get(name, "")
        prose, _ = strip_fences(content)
        words = count_words(prose)
        total += words
        limit = round(cap * multiplier)
        status = "ok"
        if words > limit:
            status = "OVER"
            failures.append(f"{name}: {words} prose words, cap {limit}")
        if not content.strip():
            failures.append(f"{name}: empty")
        rows.append((name, words, limit, status))

    verdict = by_name.get("Verdict", "")
    if not [r for r in table_rows(verdict) if r and r[0] != "Metric"]:
        failures.append("Verdict: needs the Metric / Value / Note table (tiles)")

    changes = by_name.get("Changes", "")
    diffs = [b for lang, b in fences(changes) if lang == "diff"]
    if len(diffs) > MAX_HUNKS:
        failures.append(f"Changes: {len(diffs)} diff hunks, cap {MAX_HUNKS}")
    for n, block in enumerate(diffs, start=1):
        if len(block) > MAX_HUNK_LINES:
            failures.append(f"Changes: hunk {n} is {len(block)} lines, cap {MAX_HUNK_LINES}")
    if not re.search(r"^### ", changes, flags=re.M):
        failures.append("Changes: group by service with ### ServiceName headings")
    failures += check_changes_diagram(changes, slices)
    for r in table_rows(changes):
        if len(r) >= 2 and r[0].lower() not in ("slice", "") and r[1].strip().lower() != "none" and not re.fullmatch(r"`[^`]+`", r[1].strip()):
            failures.append(f"Changes: File cell must be a backticked repo path, or none: '{r[1][:40]}'")
    hunk_titles = len(re.findall(r"^#### ", changes, flags=re.M))
    if hunk_titles != len(diffs):
        failures.append(f"Changes: {hunk_titles} #### hunk titles but {len(diffs)} diff fences; pair them one to one")

    findings = by_name.get("Findings", "")
    frows = [r for r in table_rows(findings) if r and r[0].lower() != "severity"]
    for r in frows:
        if len(r) < 4:
            failures.append(f"Findings: row needs Severity | Location | Finding | Status | Note: {r[:2]}")
            continue
        if r[0].lower() not in ("high", "medium", "low", "info"):
            failures.append(f"Findings: severity must be high, medium, low or info: '{r[0]}'")
        if r[3].lower() not in ("fixed", "accepted", "open"):
            failures.append(f"Findings: status must be fixed, accepted or open: '{r[3]}'")
        if r[3].lower() == "accepted" and (len(r) < 5 or not r[4].strip()):
            failures.append(f"Findings: accepted finding needs a reason in Note: '{r[2][:40]}'")

    qa = by_name.get("QA report", "")
    scenarios = re.findall(r"^#### .+?`(Acceptance test|Manual test)`\s+\*\*(Pass|Fail|Blocked)\*\*", qa, flags=re.M)
    if not scenarios and not re.search(r"\*\*No QA run\.?\*\*", qa):
        failures.append("QA report: no scenario headings of the form '#### Title `Acceptance test` **Pass**'; if nothing was run, open with **No QA run.** and list everything under Not covered")
    gherkin = [b for lang, b in fences(qa) if lang == "gherkin"]
    if len(gherkin) != len(scenarios):
        failures.append(f"QA report: {len(scenarios)} scenarios but {len(gherkin)} gherkin fences")
    if len(re.findall(r"^Evidence:", qa, flags=re.M)) < len(scenarios):
        failures.append("QA report: every scenario needs an Evidence line")
    fails = [s for s in scenarios if s[1] != "Pass"]
    if fails and len(re.findall(r"^Classification:", qa, flags=re.M)) < len(fails):
        failures.append("QA report: every Fail or Blocked scenario needs a Classification line")
    if "Not covered" not in qa:
        failures.append("QA report: state what is Not covered (or 'Not covered: nothing')")
    if re.search(r"\b(WebApplicationFactory|InMemory|\.Tests\b)", qa):
        failures.append("QA report: unit and integration suites are not QA; remove them")
    evidence_failures, evidence_images, evidence_videos = check_evidence(qa, multiplier)
    failures += evidence_failures

    rollout = by_name.get("Rollout", "")
    items = re.findall(r"^\s*[-*]\s+\[[xX ]\]", rollout, flags=re.M)
    if not items:
        failures.append("Rollout: needs '- [ ] step' checklist items")
    if len(items) > MAX_ROLLOUT_ITEMS:
        failures.append(f"Rollout: {len(items)} items, cap {MAX_ROLLOUT_ITEMS}")

    if WALKTHROUGH in by_name:
        walk_failures, spoken, spoken_cap = check_walkthrough(by_name[WALKTHROUGH], by_name, multiplier)
        failures += walk_failures
        rows.append((WALKTHROUGH + " (spoken)", spoken, spoken_cap, "OVER" if spoken > spoken_cap else "ok"))

    report_banned(body, REVIEW_BANNED, failures, strip_code=True)

    print(f"{'section':<28}{'words':>7}{'cap':>6}  status")
    for name, words, limit, status in rows:
        print(f"{name:<28}{words:>7}{limit:>6}  {status}")
    print(f"{'total prose':<28}{total:>7}{round(sum(c for _, c in REVIEW_SECTIONS) * multiplier):>6}")
    print(f"hunks {len(diffs)}/{MAX_HUNKS}, findings {len(frows)}, qa scenarios {len(scenarios)}, evidence images {evidence_images}, evidence videos {evidence_videos}, rollout items {len(items)}")
    return report(failures)


def main(kind=None, argv=None):
    ap = add_profile_arg(argparse.ArgumentParser(description=__doc__.splitlines()[0]))
    ap.add_argument("source")
    ap.add_argument("--kind", choices=("plan", "review"), default=kind,
                    help="rule set; inferred from the sections and front matter when omitted")
    args = ap.parse_args(argv)

    global SOURCE_DIR
    SOURCE_DIR = Path(args.source).resolve().parent
    text = Path(args.source).read_text(encoding="utf-8")
    meta, body = split_front_matter(text)
    document_kind = args.kind or infer_kind(meta, [name for name, _ in split_sections(body)])
    size = meta.get("size", "standard")
    if size not in SIZE_MULTIPLIER:
        print(f"size must be one of {sorted(SIZE_MULTIPLIER)}, got '{size}'")
        return 1
    multiplier = SIZE_MULTIPLIER[size]
    profile = resolve_profile(explicit=args.profile)
    if document_kind == "plan":
        present = [name for name, _ in split_sections(body)]
        return check_plan(meta, body, multiplier, expected_plan_sections(profile, present),
                          disallowed_plan_sections(profile, present))
    return check_review(meta, body, multiplier, review_slices(profile))


if __name__ == "__main__":
    sys.exit(main())
