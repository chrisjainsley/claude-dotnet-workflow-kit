#!/usr/bin/env python
"""Score the profile's review checks against a diff with Jev, TypeSafe's System One model.

    python jev_checks.py --range origin/main...HEAD [--profile <file>] [--out <json>]
    python jev_checks.py --diff-file <patch> [--rules <rules.json>] [--dry-run]
    python jev_checks.py --extract CLAUDE.md AGENTS.md [--out <rules.json>]
    python jev_checks.py --check-rules

Every added hunk of the diff becomes one request carrying one choice question per
applicable rule (violates / follows / not_applicable). The probability of `violates`
lands in a band from the profile's jev thresholds: at or above flag_at it is a finding at
the rule's severity, between review_at and flag_at it is a low finding to confirm by
reading, below that it is silent. Files matching the review builder's secret patterns
never leave the machine.

`--extract` turns CLAUDE.md-style files into rules of the same shape, so the conventions
reviewer's rubric can be scored the same way. `--check-rules` asks whether each profile
check could be verified from a hunk alone and warns about the ones that cannot.

Talks to https://api.typesafe.ai directly over HTTP and needs TYPESAFE_API_KEY in the
environment, or a `jev` MCP server entry in ~/.claude.json that carries it. Exit 2 when
Jev is unavailable so a caller can record the run as skipped and carry on. Never prints
the key.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_profile import CHECK_KEYS, add_profile_arg, enabled_checks, get, resolve_profile, validate, validate_checks  # noqa: E402
from render import SECRET_PATTERNS  # noqa: E402

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
CHUNK_CHARS = 12000
EXTRACT_BATCH = 32
TIMEOUT_SECONDS = 10
RETRY_STATUSES = (429, 529)
MAX_ATTEMPTS = 3
KEY_ENV = "TYPESAFE_API_KEY"
MCP_NAME = "jev"

VIOLATION_CRITERIA = {
    "violates": "One or more added lines break the rule as written.",
    "follows": "The added lines are covered by the rule and respect it.",
    "not_applicable": "The rule does not speak to anything in these lines.",
}
EXTRACT_CRITERIA = {
    "rule_must": "A mandatory instruction about code: never, must, must not, always, do not.",
    "rule_prefer": "A preference about code: prefer, should, avoid, use X over Y.",
    "example": "A right and wrong example of code style with no imperative sentence.",
    "prose": "Narrative, architecture description, headings, or anything not checkable on a diff.",
}
EXTRACT_SEVERITY = {"rule_must": "high", "rule_prefer": "medium", "example": "low"}


class JevUnavailable(Exception):
    """Raised when no key exists or the API cannot answer; the caller records a skip.

    `partial` carries whatever a scoring run had produced before the failure, so the
    findings already paid for are written out rather than lost."""

    def __init__(self, reason, partial=None):
        super().__init__(reason)
        self.partial = partial


# --- key -----------------------------------------------------------------------------


def resolve_key(env=None, claude_json=None):
    """(key, source) from the environment, then the jev MCP entry in ~/.claude.json."""
    env = os.environ if env is None else env
    if env.get(KEY_ENV):
        return env[KEY_ENV], "env"
    path = Path(claude_json) if claude_json else Path.home() / ".claude.json"
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None, None
    scopes = [data] + list((data.get("projects") or {}).values())
    for scope in scopes:
        server = ((scope or {}).get("mcpServers") or {}).get(MCP_NAME) or {}
        key = (server.get("env") or {}).get(KEY_ENV)
        if key:
            return key, "mcp config"
    return None, None


def require_key():
    key, source = resolve_key()
    if not key:
        raise JevUnavailable(f"no {KEY_ENV} and no {MCP_NAME} MCP entry")
    return key, source


# --- diff ----------------------------------------------------------------------------

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
C_ESCAPE = re.compile(r"\\(?:([0-7]{1,3})|(.))")
C_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def unquote_path(target):
    """git quotes non-ASCII paths as "b/\303\234..." unless core.quotePath is off; undo that."""
    if not (len(target) >= 2 and target[0] == '"' and target[-1] == '"'):
        return target
    inner = target[1:-1]
    out = bytearray()
    pos = 0
    for match in C_ESCAPE.finditer(inner):
        out += inner[pos:match.start()].encode("utf-8")
        if match.group(1):
            out.append(int(match.group(1), 8))
        else:
            out += C_SIMPLE.get(match.group(2), match.group(2)).encode("utf-8")
        pos = match.end()
    out += inner[pos:].encode("utf-8")
    return out.decode("utf-8", errors="replace")


def parse_diff(text):
    """Hunks with added lines: {path, line, text}. `line` is the first added line number."""
    hunks = []
    path = None
    current = None

    def close():
        if current and current["added"]:
            hunks.append({"path": current["path"], "line": current["line"], "start": current["start"],
                          "text": "\n".join(current["lines"])})

    for raw in text.splitlines():
        if raw.startswith("diff --git"):
            close()
            current = None
            path = None
            continue
        if current is None and raw.startswith("+++ "):
            target = unquote_path(raw[4:].strip())
            path = None if target == "/dev/null" else re.sub(r"^b/", "", target)
            continue
        if current is None and not HUNK_HEADER.match(raw):
            continue  # --- header, index, mode and binary lines
        header = HUNK_HEADER.match(raw)
        if header:
            close()
            start = int(header.group(1))
            current = {"path": path, "line": None, "start": start, "lines": [raw], "added": 0, "new": start} if path else None
            continue
        if current is None:
            continue
        current["lines"].append(raw)
        if raw.startswith("+"):
            current["added"] += 1
            if current["line"] is None:
                current["line"] = current["new"]
        if not raw.startswith("-") and not raw.startswith("\\"):
            current["new"] += 1
    close()
    return hunks


def chunk_text(text, limit=CHUNK_CHARS):
    """Split on line boundaries so no chunk exceeds `limit` characters; a single longer line is cut hard."""
    if len(text) <= limit:
        return [text]
    chunks, current, size = [], [], 0
    for line in text.splitlines():
        pieces = [line[i:i + limit] for i in range(0, len(line), limit)] or [""]
        for piece in pieces:
            if current and size + len(piece) + 1 > limit:
                chunks.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def chunk_hunk(hunk, limit=CHUNK_CHARS):
    """(text, first added line) per chunk that still carries an added line."""
    out = []
    new_line = hunk["start"]
    for chunk in chunk_text(hunk["text"], limit):
        first = None
        for line in chunk.splitlines():
            if HUNK_HEADER.match(line):
                continue
            if line.startswith("+") and first is None:
                first = new_line
            if not line.startswith("-") and not line.startswith("\\"):
                new_line += 1
        if first is not None:
            out.append((chunk, first))
    return out


def glob_to_regex(pattern):
    out = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


def path_matches(pattern, path):
    return bool(glob_to_regex(pattern).match(path.replace("\\", "/")))


def git_diff(range_spec, repo=None):
    run = subprocess.run(["git", "diff", range_spec], cwd=repo, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if run.returncode != 0:
        raise SystemExit(f"git diff failed: {run.stderr.strip()}")
    return run.stdout


def git_head(repo=None):
    run = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    return run.stdout.strip() if run.returncode == 0 else ""


# --- transport -----------------------------------------------------------------------


def default_transport(body_bytes, headers):
    request = urllib.request.Request(API_URL, data=body_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise JevUnavailable(f"request failed: {error}") from error


def post(body, key, transport=None, sleep=time.sleep):
    """POST one System One request; retries 429 and 529 with backoff. Returns the answers."""
    transport = transport or default_transport
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = json.dumps(body).encode("utf-8")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status, text = transport(payload, headers)
        if status == 200:
            try:
                return json.loads(text).get("answers") or {}
            except ValueError as error:
                raise JevUnavailable("response was not JSON") from error
        if status in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
            sleep(0.5 * (2 ** (attempt - 1)))
            continue
        raise JevUnavailable(f"api responded {status}")
    raise JevUnavailable("retries exhausted")


# --- scoring -------------------------------------------------------------------------


def build_request(path, text, rules):
    questions = {
        rule["id"]: {
            "type": "choice",
            "instructions": f"Do the added lines (prefixed +) in this hunk violate the rule: {rule['rule']}",
            "criteria": VIOLATION_CRITERIA,
        }
        for rule in rules
    }
    return {"state": {"path": path, "hunk": text}, "model": MODEL, "questions": questions}


def band(probability, thresholds):
    if probability >= thresholds["flag_at"]:
        return "flag"
    if probability >= thresholds["review_at"]:
        return "review"
    return None


def score_hunks(hunks, rules, thresholds, key=None, transport=None, dry_run=False):
    """Return (findings, requests) where requests is the list of bodies built."""
    findings, requests = [], []
    for hunk in hunks:
        applicable = [r for r in rules if path_matches(r["files"], hunk["path"])]
        if not applicable:
            continue
        for chunk, first_line in chunk_hunk(hunk):
            body = build_request(hunk["path"], chunk, applicable)
            requests.append(body)
            if dry_run:
                continue
            try:
                answers = post(body, key, transport)
            except JevUnavailable as error:
                raise JevUnavailable(f"{error} after {len(requests) - 1} of the requests", (findings, requests[:-1])) from error
            for rule in applicable:
                answer = answers.get(rule["id"]) or {}
                probability = float((answer.get("probabilities") or {}).get("violates", 0.0))
                which = band(probability, thresholds)
                if not which:
                    continue
                findings.append({
                    "severity": rule["severity"] if which == "flag" else "low",
                    "location": f"{hunk['path']}:{first_line}",
                    "finding": rule["rule"],
                    "source": f"checks:{rule['id']}",
                    "probability": round(probability, 2),
                    "note": "" if which == "flag" else f"Jev {probability:.2f}, confirm by reading",
                })
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3), -f["probability"], f["location"]))
    return findings, requests


def split_hunks(hunks):
    """Separate hunks whose path matches the secret patterns from the ones Jev may see."""
    safe, skipped = [], []
    for hunk in hunks:
        if SECRET_PATTERNS.search(hunk["path"]):
            skipped.append(f"{hunk['path']}: secret pattern, not sent")
        else:
            safe.append(hunk)
    return safe, sorted(set(skipped))


# --- rubric extraction ---------------------------------------------------------------

BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def candidate_lines(path):
    """(line number, text) for every bullet or sentence line outside fences and headings."""
    items = []
    in_fence = False
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith("#") or line.startswith("|") or line.startswith("<"):
            continue
        text = BULLET.sub("", line).strip()
        if len(text.split()) >= 3:
            items.append((number, text))
    return items


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "rule"


def rule_prefix(path):
    """The path relative to the working directory, minus the suffix, so two CLAUDE.md files never share ids.

    A file outside the working directory (the user's ~/.claude/CLAUDE.md) gets its name plus a
    short hash of its full path, so it cannot collide with a repo file of the same name."""
    import hashlib
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(Path.cwd().resolve())
    except ValueError:
        digest = hashlib.sha1(resolved.as_posix().encode("utf-8")).hexdigest()[:6]
        return f"{resolved.stem}-{digest}"
    return relative.with_suffix("").as_posix()


def extract_rules(paths, key=None, transport=None, dry_run=False, keep_at=0.5):
    rules, requests = [], []
    for path in paths:
        items = candidate_lines(path)
        stem = slug(rule_prefix(path))
        for start in range(0, len(items), EXTRACT_BATCH):
            batch = items[start:start + EXTRACT_BATCH]
            body = {
                "state": [{"id": f"{stem}-{number}", "text": text} for number, text in batch],
                "model": MODEL,
                "questions": {
                    f"{stem}-{number}": {
                        "type": "choice",
                        "instructions": f"Classify item {stem}-{number}: is it a checkable coding rule?",
                        "criteria": EXTRACT_CRITERIA,
                    }
                    for number, _ in batch
                },
            }
            requests.append(body)
            if dry_run:
                continue
            answers = post(body, key, transport)
            for number, text in batch:
                item_id = f"{stem}-{number}"
                answer = answers.get(item_id) or {}
                choice = answer.get("choice")
                probability = float((answer.get("probabilities") or {}).get(choice, 0.0)) if choice else 0.0
                if choice in EXTRACT_SEVERITY and probability >= keep_at:
                    rules.append({
                        "id": item_id, "rule": text, "severity": EXTRACT_SEVERITY[choice],
                        "files": "**/*", "source": f"{path}:{number}", "probability": round(probability, 2),
                    })
    return rules, requests


def check_rules(rules, key=None, transport=None, dry_run=False, warn_below=0.5):
    """[(rule id, probability)] for rules Jev doubts a reader could verify from a hunk."""
    if not rules:
        return [], []
    body = {
        "state": [{"id": r["id"], "rule": r["rule"]} for r in rules],
        "model": MODEL,
        "questions": {
            r["id"]: {
                "type": "noul",
                "instructions": f"Could a reader decide whether rule {r['id']} is broken by looking at one changed hunk of one file, with no other file, no test run and no knowledge of intent?",
                "criteria": {"true": "The rule names a type, call, pattern or shape that is visible or absent in the changed lines themselves.",
                             "false": "Deciding needs another file (a README, a test, a migration elsewhere), runtime behaviour, or the author's intent."},
            }
            for r in rules
        },
    }
    if dry_run:
        return [], [body]
    answers = post(body, key, transport)
    doubtful = []
    for rule in rules:
        probability = float((answers.get(rule["id"]) or {}).get("noul", 1.0))
        if probability < warn_below:
            doubtful.append((rule["id"], round(probability, 2)))
    return doubtful, [body]


# --- output --------------------------------------------------------------------------


def markdown_table(findings):
    lines = ["| Severity | Location | Finding | Source | Jev |", "|---|---|---|---|---|"]
    for f in findings:
        note = f" ({f['note']})" if f.get("note") else ""
        lines.append(f"| {f['severity']} | {f['location']} | {f['finding']}{note} | {f['source']} | {f['probability']:.2f} |")
    return "\n".join(lines)


def load_rules_file(path):
    """A bare list of checks, or the JSON `--extract --out` wrote (its rules live under `rules`).

    Returns (rules, problems). A missing file is not an error: the sweep passes the path
    `--extract` would have written even when extraction was skipped."""
    file = Path(path)
    if not file.exists():
        return [], [f"rules file {path} not found; scoring the profile checks only"]
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except ValueError as error:
        return [], [f"rules file {path} is not JSON: {error}"]
    if isinstance(data, dict):
        data = data.get("rules") or []
    # --extract output carries source and probability alongside the check keys; drop them before validating
    data = [{k: v for k, v in c.items() if k in CHECK_KEYS} if isinstance(c, dict) else c for c in data]
    problems = [f"rules file {path}: {problem}" for problem in validate_checks({"checks": data})]
    return (enabled_checks({"checks": data}) if not problems else []), problems


def main(argv=None):
    ap = add_profile_arg(argparse.ArgumentParser(description=__doc__.splitlines()[0]))
    ap.add_argument("--range", help="git diff range, for example origin/main...HEAD")
    ap.add_argument("--diff-file", help="a unified diff to score instead of running git")
    ap.add_argument("--repo", help="repository to run git in; default: current directory")
    ap.add_argument("--rules", help="extra rules JSON (same shape as the profile's checks)")
    ap.add_argument("--extract", nargs="+", metavar="MD", help="extract rules from these markdown files and stop")
    ap.add_argument("--check-rules", action="store_true", help="ask whether each profile check is verifiable from a hunk")
    ap.add_argument("--out", help="write the JSON result here")
    ap.add_argument("--dry-run", action="store_true", help="build the requests, send nothing")
    args = ap.parse_args(argv)

    profile = resolve_profile(explicit=args.profile)
    problems = validate(profile)
    if problems:
        for problem in problems:
            print(f"invalid: {problem}", file=sys.stderr)
        return 1
    thresholds = {"flag_at": get(profile, "jev.flag_at"), "review_at": get(profile, "jev.review_at")}
    rules = enabled_checks(profile)
    if args.rules:
        extra, problems = load_rules_file(args.rules)
        for problem in problems:
            print(f"warning: {problem}" if extra or "not found" in problem else f"invalid: {problem}", file=sys.stderr)
        if problems and "not found" not in problems[0]:
            return 1
        rules += extra
    if not (args.extract or args.check_rules or args.range or args.diff_file):
        print("usage: --range or --diff-file is required (or --extract / --check-rules)", file=sys.stderr)
        return 1

    key, source = (None, "dry-run")
    hunks, skipped, findings, requests, partial_error = [], [], [], [], ""
    try:
        if not args.dry_run:
            key, source = require_key()

        if args.extract:
            extracted, requests = extract_rules(args.extract, key, None, args.dry_run)
            result = {"at": now(), "key_source": source, "requests": len(requests), "rules": extracted}
            if args.dry_run:
                result["dry_run"] = requests
            write_out(args.out, result if args.out else None)
            print(json.dumps(extracted if not args.dry_run else requests, indent=2))
            return 0

        if args.check_rules:
            doubtful, requests = check_rules(rules, key, None, args.dry_run)
            for rule_id, probability in doubtful:
                print(f"warning: {rule_id} may not be verifiable from a diff hunk (Jev {probability:.2f})")
            if not doubtful and not args.dry_run:
                print(f"{len(rules)} rule{'s' if len(rules) != 1 else ''} look verifiable from a hunk")
            if args.dry_run:
                print(json.dumps(requests, indent=2))
            return 0

        if not rules:
            print("no checks in the profile and no --rules file; nothing to score")
            return 0
        diff = Path(args.diff_file).read_text(encoding="utf-8") if args.diff_file else git_diff(args.range, args.repo)
        hunks, skipped = split_hunks(parse_diff(diff))
        findings, requests = score_hunks(hunks, rules, thresholds, key, None, args.dry_run)
    except JevUnavailable as error:
        print(f"jev unavailable: {error}", file=sys.stderr)
        if not error.partial:
            return 2
        findings, requests = error.partial
        partial_error = str(error)

    result = {
        "at": now(),
        "range": args.range or args.diff_file,
        "commit": git_head(args.repo) if args.range else "",
        "key_source": source,
        "hunks": len(hunks),
        "requests": len(requests),
        "rules": [r["id"] for r in rules],
        "findings": findings,
        "skipped": skipped,
    }
    if partial_error:
        result["partial"] = partial_error
    if args.dry_run:
        result["dry_run"] = requests
    write_out(args.out, result)
    if partial_error:
        print(markdown_table(findings) if findings else "No findings before the failure.")
        print(f"\npartial: {len(requests)} requests answered before the failure; results written, run again to finish")
        for line in skipped:
            print(f"skipped: {line}")
        return 2
    if args.dry_run:
        print(f"dry run: {len(requests)} request{'s' if len(requests) != 1 else ''} for {len(hunks)} hunks, nothing sent")
        for body in requests:
            print(f"  {body['state']['path']}: {', '.join(body['questions'])}")
    else:
        print(markdown_table(findings) if findings else "No findings above the review threshold.")
        print(f"\n{len(hunks)} hunks, {len(requests)} requests, {len(findings)} findings, key from {source}")
    for line in skipped:
        print(f"skipped: {line}")
    return 0


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_out(path, result):
    if path and result is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(result, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
