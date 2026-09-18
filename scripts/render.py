#!/usr/bin/env python
"""Render a plan.md or a review.md into the shared HTML page template.

Usage:
  python render.py plans/<slug>/plan.md --out plans/<slug>/plan.html
  python render.py plans/<slug>/review.md --out plans/<slug>/review.html --range <a>..<b>

`--kind plan|review` picks the document mode; without it the kind is inferred from
the ## section names, then from the front matter. `--template` defaults to the
repository's assets/page.html.
`--profile` names the kit profile; by default the project then user file is read.
Its `branding` flag (default true) adds the Delivery Labs colours and the attribution
footer; false renders the neutral palette with no footer.

The markdown subset is deliberately small: ## sections, ### and #### subheads,
paragraphs, bullet and numbered lists (one nesting level), pipe tables, fenced code
(```mermaid becomes a native mermaid block), inline code, bold, italic, links.
HTML comments in the source are dropped so skeleton hints never reach the page.
Images (`![caption](context/frame.png)`, path relative to the source) are inlined as
data URIs, downscaled to 1600px wide when Pillow is installed, and consecutive images
form a grid.

Plan mode: the "Context" section renders collapsed inside a <details> element, each
section head carries an onion ring marking its architecture layer, and "Open
questions" becomes the answer form. Each numbered item is a question, nested
"- [x] **Label.** detail" lines become radio options ([x] is the recommended,
preselected one), and a question with no options becomes a free-text answer.
Question ids derive from the title text, so a republish keeps answers already stored
as long as the title is unchanged.

Review mode: Verdict becomes stat tiles, Plan versus delivered and Findings render
status pills, Changes pairs "#### title" with a ```diff fence into collapsed hunks
and links backticked File cells to full per-file diffs pulled from git for --range
(derived from the front matter when omitted), QA report renders scenario cards,
Rollout renders a persistent checklist, and Decision gets the approve /
request-changes form.
"""
import argparse
import base64
import hashlib
import html
import io
import mimetypes
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # Pillow is optional; images are inlined at their original size without it
    Image = None

DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "page.html"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_profile import add_profile_arg, resolve_profile  # noqa: E402

# Delivery Labs branding: the profile's `branding` flag (default true) switches it off.
# Colours follow deliverylabs.co: indigo accents on a gray-900 dark ground. Only the
# accent tokens change; warn/bad/ok keep their meaning.
BRAND_URL = "https://deliverylabs.co/workflow-kit"
BRAND_NAME = "Delivery Labs"
BRAND_LIGHT = "--accent: #4F46E5; --accent-soft: #EEF2FF; --hl-kw: #4F46E5; --hl-ty: #6D28D9;"
BRAND_DARK = ("--paper: #111827; --card: #1F2937; --line: #374151; --muted: #9CA3AF; --ink: #F3F4F6; "
              "--accent: #818CF8; --accent-soft: #1E1B4B; --code-bg: #0B1120; --hl-kw: #A5B4FC; --hl-ty: #C4B5FD;")
BRAND_STYLE = "\n".join([
    "<style>",
    ":root { " + BRAND_LIGHT + " }",
    '@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ' + BRAND_DARK + " } }",
    ':root[data-theme="dark"] { ' + BRAND_DARK + " }",
    "</style>",
])
BRAND_FOOTER = (
    '<footer class="attribution">'
    f'<a class="wordmark" href="{BRAND_URL}">{BRAND_NAME}</a>'
    '<span class="sep" aria-hidden="true">|</span>'
    f'<span>Built with the <a href="{BRAND_URL}">dotnet-workflow-kit</a>.</span>'
    '</footer>'
)

SOURCE_DIR = Path(".")
REPO_DIR = Path(".")
KIND = "plan"
MAX_IMAGE_WIDTH = 1600
MAX_FILE_DIFF_LINES = 400
SECRET_PATTERNS = re.compile(r"(appsettings[^/]*\.json|local\.settings\.json|\.tfvars|\.env(\.|$)|secrets?\.(json|ya?ml)|\.pfx|\.pem)$", re.I)
META = {}
DIFF_RANGE = None
FILE_STATS = {}
USED_FILES = []
WARNINGS = []

NON_LAYER_SECTIONS = {
    "Context", "Requirement", "Specs", "Tests", "Decisions",
    "Risks and rollout", "Open questions",
}
SHORT = {
    "Risks and rollout": "Risks", "Open questions": "Questions",
    "Plan versus delivered": "Plan vs delivered", "Contracts and coordination": "Contracts",
    "QA report": "QA",
}
LANG_ALIAS = {"cs": "csharp", "c#": "csharp", "gql": "graphql", "feature": "gherkin",
              "sh": "bash", "ps1": "powershell", "patch": "diff"}
QUESTIONS_SECTION = "Open questions"
CONTEXT_SECTION = "Context"
REVIEW_MODES = {"Verdict": "verdict", "Plan versus delivered": "plan", "Changes": "changes",
                "Findings": "findings", "QA report": "qa", "Rollout": "rollout"}
PLAN_CHIP_KEYS = ("ticket", "branch", "base", "size", "date")
REVIEW_CHIP_KEYS = ("state", "pr", "branch", "base", "commits", "files", "ci", "deployed", "date")
PILL_WORDS = {"done", "changed", "dropped", "fixed", "accepted", "open", "high", "medium",
              "low", "info", "pass", "fail", "blocked"}
PLAN_HINT = "Answers sent from this page reach Claude on the next turn. The plan is rebuilt and republished at this URL."
REVIEW_HINT = "Ticks and the decision sent from this page reach Claude on the next turn. The review is rebuilt and republished at this URL."

IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
LIST_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
CHECK_RE = re.compile(r"^\s*[-*]\s+\[([xX ])\]\s+(.*)$")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def inline(text):
    text = html.escape(text, quote=False)
    codes = []

    def stash(match):
        codes.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def pill(text):
    word = text.strip().lower()
    if word in PILL_WORDS:
        return f'<span class="pill pill-{word}">{html.escape(text.strip())}</span>'
    return inline(text)


def image_data_uri(path):
    file = (SOURCE_DIR / path).resolve()
    if not file.exists():
        return None
    data = file.read_bytes()
    mime = mimetypes.guess_type(file.name)[0] or "image/png"
    if Image is not None and mime in ("image/png", "image/jpeg", "image/webp"):
        with Image.open(io.BytesIO(data)) as img:
            if img.width > MAX_IMAGE_WIDTH:
                img = img.resize((MAX_IMAGE_WIDTH, round(img.height * MAX_IMAGE_WIDTH / img.width)))
                buffer = io.BytesIO()
                img.save(buffer, format="PNG", optimize=True)
                data, mime = buffer.getvalue(), "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def render_figures(lines):
    out = ['<div class="figures">']
    for line in lines:
        alt, path = IMAGE_RE.match(line.strip()).groups()
        uri = image_data_uri(path)
        if uri is None:
            out.append(f'<figure class="missing"><figcaption>Missing image: {html.escape(path)}</figcaption></figure>')
            continue
        out.append(f'<figure><img src="{uri}" alt="{html.escape(alt, quote=True)}" loading="lazy"><figcaption>{inline(alt)}</figcaption></figure>')
    out.append("</div>")
    return "".join(out)


def parse_table(lines):
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
    return [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        WARNINGS.append(f"git {' '.join(args[:2])} failed: {getattr(exc, 'stderr', exc) or exc}".strip())
        return ""


def derive_range(meta):
    if meta.get("state", "").lower() == "merged":
        m = re.search(r"\b[0-9a-f]{7,40}\b", meta.get("commits", ""))
        if m:
            return f"{m.group(0)}^..{m.group(0)}"
        WARNINGS.append("state is merged but no sha in 'commits'; pass --range")
        return None
    return f"origin/{meta.get('base', 'dev')}...HEAD"


def load_file_stats():
    if not DIFF_RANGE:
        return
    for line in git("diff", "--numstat", DIFF_RANGE).splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            adds, dels, path = parts
            FILE_STATS[path] = (adds, dels)


def resolve_path(text):
    if text in FILE_STATS:
        return text
    tail = text.replace("\\", "/").lstrip("./")
    hits = [p for p in FILE_STATS if p == tail or p.endswith("/" + tail)]
    if len(hits) == 1:
        return hits[0]
    if hits:
        WARNINGS.append(f"'{text}' matches {len(hits)} changed files; use a longer path")
    return None


def file_anchor(path):
    return "file-" + slug(path)


def github_url(path):
    m = re.match(r"(https://github\.com/[^/]+/[^/]+)/pull/(\d+)", META.get("pr", ""))
    if not m:
        return None
    anchor = "diff-" + hashlib.sha256(path.encode("utf-8")).hexdigest()
    if META.get("state", "").lower() == "merged":
        sha = re.search(r"\b[0-9a-f]{7,40}\b", META.get("commits", ""))
        if sha:
            return f"{m.group(1)}/commit/{sha.group(0)}#{anchor}"
    return f"{m.group(1)}/pull/{m.group(2)}/files#{anchor}"


def file_cell(cell):
    m = re.fullmatch(r"`([^`]+)`", cell.strip())
    if not m:
        return inline(cell)
    path = resolve_path(m.group(1))
    if path is None:
        if m.group(1).lower() != "none":
            WARNINGS.append(f"'{m.group(1)}' is not in the diff for {DIFF_RANGE}; cell left unlinked")
        return inline(cell)
    if path not in USED_FILES:
        USED_FILES.append(path)
    return f'<a class="filelink" href="#{file_anchor(path)}"><code>{html.escape(m.group(1))}</code></a>'


def render_file_diffs():
    if not USED_FILES:
        return ""
    out = ['<div class="filediffs"><h4>File diffs</h4>']
    for path in USED_FILES:
        adds, dels = FILE_STATS.get(path, ("?", "?"))
        gh = github_url(path)
        gh_link = f'<a class="gh" href="{html.escape(gh, quote=True)}" target="_blank" rel="noopener">GitHub</a>' if gh else ""
        head = (f'<summary><code>{html.escape(path)}</code><span class="fstat"><span class="fadd">+{adds}</span> <span class="fdel">-{dels}</span></span>{gh_link}</summary>')
        if SECRET_PATTERNS.search(path):
            body = '<p class="fnote">Diff not embedded: this file can hold configuration secrets. Use the GitHub link.</p>'
        else:
            lines = git("diff", DIFF_RANGE, "--", path).splitlines()
            note = ""
            if len(lines) > MAX_FILE_DIFF_LINES:
                note = f'<p class="fnote">Showing the first {MAX_FILE_DIFF_LINES} of {len(lines)} lines. The GitHub link has the rest.</p>'
                lines = lines[:MAX_FILE_DIFF_LINES]
            body = note + f'<pre><code class="language-diff">{html.escape(chr(10).join(lines), quote=False)}</code></pre>'
        out.append(f'<details class="hunk filediff" id="{file_anchor(path)}">{head}{body}</details>')
    out.append("</div>")
    return "".join(out)


def render_table(lines, pill_columns=(), file_column=None):
    rows = parse_table(lines)
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    out = ['<div class="table-wrap"><table><thead><tr>'] + [f"<th>{inline(c)}</th>" for c in head] + ["</tr></thead><tbody>"]
    for row in body:
        cells = []
        for idx, cell in enumerate(row):
            if idx == file_column:
                cells.append(f"<td>{file_cell(cell)}</td>")
            else:
                cells.append(f"<td>{pill(cell) if idx in pill_columns else inline(cell)}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_tiles(lines):
    rows = parse_table(lines)[1:]
    out = ['<div class="tiles">']
    for row in rows:
        metric = row[0] if row else ""
        value = row[1] if len(row) > 1 else ""
        note = row[2] if len(row) > 2 else ""
        out.append(f'<div class="tile"><div class="tile-metric">{inline(metric)}</div><div class="tile-value">{inline(value)}</div><div class="tile-note">{inline(note)}</div></div>')
    out.append("</div>")
    return "".join(out)


def render_list(items, ordered):
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    for text, children in items:
        out.append(f"<li>{inline(text)}")
        if children:
            out.append(render_list(children, ordered=False))
        out.append("</li>")
    out.append(f"</{tag}>")
    return "".join(out)


def parse_list(lines, i):
    items = []
    while i < len(lines):
        m = LIST_RE.match(lines[i])
        if not m:
            if lines[i].startswith("  ") and items and lines[i].strip():
                target = items[-1][1][-1] if items[-1][1] else items[-1]
                target[0] += " " + lines[i].strip()
                i += 1
                continue
            break
        if len(m.group(1)) == 0:
            items.append([m.group(3), []])
        elif items:
            items[-1][1].append([m.group(3), []])
        i += 1
    return items, i


def render_checklist(lines):
    out = ['<ul class="checklist">']
    for line in lines:
        m = CHECK_RE.match(line)
        cid = slug(m.group(2))[:60]
        checked = " checked" if m.group(1).lower() == "x" else ""
        out.append(f'<li><label><input type="checkbox" data-step="{cid}"{checked}><span>{inline(m.group(2))}</span></label></li>')
    out.append("</ul>")
    return "".join(out)


def read_fence(lines, i):
    lang = LANG_ALIAS.get(lines[i][3:].strip().lower(), lines[i][3:].strip().lower())
    code, i = [], i + 1
    while i < len(lines) and not lines[i].startswith("```"):
        code.append(lines[i])
        i += 1
    return lang, "\n".join(code), i + 1


def render_code(lang, body):
    body = html.escape(body, quote=False)
    if lang == "mermaid":
        # The Artifact runtime renders pre.mermaid natively; the figure wrapper survives that
        # and is what the page script clicks to open the diagram full-size in a dialog.
        return (
            f'<figure class="diagram" title="Open full size">'
            f'<pre class="mermaid">{body}</pre>'
            f'<figcaption><button type="button" class="diagram-open">Open full size</button></figcaption>'
            f"</figure>"
        )
    cls = f' class="language-{lang}"' if lang else ""
    return f"<pre><code{cls}>{body}</code></pre>"


def render_blocks(lines, mode=None, state=None):
    out, i = [], 0
    tile_done = False
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            lang, body, i = read_fence(lines, i)
            out.append(render_code(lang, body))
            continue
        if line.startswith("#### "):
            title = line[5:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if mode == "changes" and j < len(lines) and lines[j].startswith("```"):
                lang, body, i = read_fence(lines, j)
                out.append(f'<details class="hunk"><summary>{inline(title)}</summary>{render_code(lang, body)}</details>')
                continue
            if mode == "qa":
                m = re.match(r"^(.*?)\s*`(Acceptance test|Manual test)`\s+\*\*(Pass|Fail|Blocked)\*\*\s*$", title)
                if m:
                    out.append(f'<h4 class="scenario-title"><span>{inline(m.group(1))}</span>{pill(m.group(2).split()[0])}{pill(m.group(3))}</h4>')
                    i += 1
                    continue
            out.append(f"<h4>{inline(title)}</h4>")
            i += 1
            continue
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:].strip())}</h3>")
            i += 1
            continue
        if IMAGE_RE.match(line.strip()):
            figures = []
            while i < len(lines) and IMAGE_RE.match(lines[i].strip()):
                figures.append(lines[i])
                i += 1
            out.append(render_figures(figures))
            continue
        if line.lstrip().startswith("|"):
            table = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            if mode == "verdict" and not tile_done:
                out.append(render_tiles(table))
                tile_done = True
            elif mode == "plan":
                out.append(render_table(table, pill_columns=(1,)))
            elif mode == "findings":
                out.append(render_table(table, pill_columns=(0, 3)))
                if state is not None:
                    for row in parse_table(table)[1:]:
                        if len(row) >= 4 and row[3].strip().lower() == "open":
                            state.append((row[1], row[2]))
            elif mode == "qa":
                out.append(render_table(table, pill_columns=(3,)))
            elif mode == "changes":
                out.append(render_table(table, file_column=1))
            else:
                out.append(render_table(table))
            continue
        if CHECK_RE.match(line) and mode == "rollout":
            items = []
            while i < len(lines) and CHECK_RE.match(lines[i]):
                items.append(lines[i])
                i += 1
            out.append(render_checklist(items))
            continue
        if LIST_RE.match(line):
            ordered = LIST_RE.match(line).group(2)[0].isdigit()
            items, i = parse_list(lines, i)
            out.append(render_list(items, ordered))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(```|#{3,4} |\s*[-*]\s|\s*\d+\.\s|\s*\||!\[)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para)
        label = re.match(r"^(Evidence|Classification|Not covered):\s*(.*)$", text, flags=re.S)
        if mode == "qa" and label:
            out.append(f'<p class="qa-{label.group(1).split()[0].lower()}"><span class="qa-label">{label.group(1)}</span> {inline(label.group(2))}</p>')
        elif mode == "qa" and text.startswith("**Not covered:**"):
            out.append(f'<p class="qa-not"><span class="qa-label">Not covered</span> {inline(text[len("**Not covered:**"):].strip())}</p>')
        else:
            out.append(f"<p>{inline(text)}</p>")
    return "\n".join(out)


def split_title(text):
    m = re.match(r"^(.+?[?.!])(\s+.*)?$", text.strip(), flags=re.S)
    if not m:
        return text.strip(), ""
    return m.group(1).strip(), (m.group(2) or "").strip()


def split_option(text):
    m = re.match(r"^\[([xX ])\]\s*(.*)$", text.strip())
    recommended = bool(m and m.group(1).lower() == "x")
    body = m.group(2) if m else text.strip()
    lm = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", body, flags=re.S)
    if lm:
        return recommended, lm.group(1).strip(), lm.group(2).strip()
    label, detail = split_title(body)
    return recommended, label.rstrip("."), detail


def render_questions(lines):
    first = next((l for l in lines if l.strip()), "")
    if not LIST_RE.match(first):
        return render_blocks(lines), 0
    i = next(n for n, l in enumerate(lines) if l.strip())
    items, _ = parse_list(lines, i)
    out = ['<form class="qform" id="qform" autocomplete="off">']
    for n, (text, options) in enumerate(items, start=1):
        title, subtitle = split_title(text)
        qid = f"q{n}-{slug(title)[:48]}"
        out.append(f'<fieldset class="q" data-qid="{qid}" data-title="{html.escape(title)}">')
        out.append(f'<legend><span class="qnum">{n}</span><span class="qtitle">{inline(title)}</span></legend>')
        if subtitle:
            out.append(f'<p class="qsub">{inline(subtitle)}</p>')
        if options:
            for opt_text, _ in options:
                recommended, label, detail = split_option(opt_text)
                checked = " checked" if recommended else ""
                badge = '<span class="badge">Recommended</span>' if recommended else ""
                out.append(
                    f'<label class="opt"><input type="radio" name="{qid}" value="{html.escape(label, quote=True)}"{checked}>'
                    f'<span class="opt-body"><span class="opt-label">{inline(label)}{badge}</span>'
                    + (f'<span class="opt-detail">{inline(detail)}</span>' if detail else "")
                    + "</span></label>"
                )
            out.append(
                f'<label class="opt other"><input type="radio" name="{qid}" value="__other__">'
                f'<input type="text" class="other-text" placeholder="Other, type your own answer"></label>'
            )
        else:
            out.append(f'<textarea name="{qid}" rows="3" placeholder="Constraints, accounts to use, files that must not move..."></textarea>')
        out.append("</fieldset>")
    out.append(
        '<div class="qfoot"><span class="qcount" id="qcount"></span>'
        '<span class="qstatus" id="qstatus"></span>'
        '<button type="submit" id="qsend">Send answers</button></div></form>'
    )
    return "\n".join(out), len(items)


def render_decision_form(open_findings, merged=False):
    out = ['<form class="dform" id="dform" autocomplete="off">']
    out.append('<fieldset class="d"><legend>Decision</legend>')
    if merged:
        approve_detail = "Post the QA report to the work item and close this review; open findings marked fix become follow-up tickets."
        changes_detail = "Say what in the notes; a follow-up branch is raised and this review is rebuilt against it."
        changes_label = "Needs follow-up"
    else:
        approve_detail = "Post the QA report to the work item, mark the PR ready, move the item to QA Ready."
        changes_detail = "Say what in the notes; the branch gets fixed and this review is rebuilt."
        changes_label = "Request changes"
    out.append(f'<label class="opt"><input type="radio" name="verdict" value="approve"><span class="opt-body"><span class="opt-label">Approve</span><span class="opt-detail">{approve_detail}</span></span></label>')
    out.append(f'<label class="opt"><input type="radio" name="verdict" value="changes"><span class="opt-body"><span class="opt-label">{changes_label}</span><span class="opt-detail">{changes_detail}</span></span></label>')
    out.append('<textarea name="notes" rows="3" placeholder="Notes for the author, optional on approve"></textarea>')
    out.append("</fieldset>")
    for n, (location, finding) in enumerate(open_findings, start=1):
        fid = f"finding-{n}"
        out.append(f'<fieldset class="d finding" data-fid="{fid}"><legend>Open finding {n}: {inline(location)}</legend><p class="qsub">{inline(finding)}</p>')
        out.append(f'<label class="opt inline"><input type="radio" name="{fid}" value="fix"><span class="opt-label">Fix before merge</span></label>')
        out.append(f'<label class="opt inline"><input type="radio" name="{fid}" value="accept"><span class="opt-label">Accept as is</span></label>')
        out.append("</fieldset>")
    out.append('<div class="qfoot"><span class="qstatus" id="dstatus"></span><button type="submit" id="dsend">Send decision</button></div></form>')
    return "".join(out)


def parse_meta(text):
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        for line in text[3:end].strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def split_document(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    meta = parse_meta(text)
    if text.startswith("---"):
        text = text[text.find("\n---", 3) + 4:]
    sections, current = [], None
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            current = [m.group(1).strip(), []]
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return meta, sections


def infer_kind(meta, section_names):
    names = set(section_names)
    if names & set(REVIEW_MODES) or "Decision" in names:
        return "review"
    if names & {"Requirement", QUESTIONS_SECTION, CONTEXT_SECTION, "Specs"}:
        return "plan"
    declared = meta.get("kind", "").strip().lower()
    if declared in ("plan", "review"):
        return declared
    if meta.get("pr") or meta.get("state"):
        return "review"
    return "plan"


def parse(text, kind=None):
    """Return (meta, [(section name, html body)], count).

    count is the number of answerable questions for a plan, the number of open
    findings for a review.
    """
    global KIND
    meta, sections = split_document(text)
    KIND = kind or infer_kind(meta, [name for name, _ in sections])
    if KIND == "plan":
        output, questions = [], 0
        for name, lines in sections:
            if name == QUESTIONS_SECTION:
                body, count = render_questions(lines)
                questions += count
            elif name == CONTEXT_SECTION:
                body = f'<details class="context"><summary>Parent feature, area and designs</summary>{render_blocks(lines)}</details>'
            else:
                body = render_blocks(lines)
            output.append((name, body))
        return meta, output, questions
    open_findings, output = [], []
    for name, lines in sections:
        mode = REVIEW_MODES.get(name)
        body = render_blocks(lines, mode, open_findings if mode == "findings" else None)
        if name == "Changes":
            body += render_file_diffs()
        if name == "Decision":
            body += render_decision_form(open_findings, merged=meta.get("state", "").lower() == "merged")
        output.append((name, body))
    return meta, output, len(open_findings)


def onion_svg(active, total=5):
    rings = []
    for idx in range(total):
        r = 6 + idx * 6
        cls = "ring active" if active == idx else "ring"
        rings.append(f'<circle class="{cls}" cx="32" cy="32" r="{r}"/>')
    return '<svg class="onion" viewBox="0 0 64 64" aria-hidden="true">' + "".join(rings) + "</svg>"


def render_chip(key, value):
    if KIND == "review" and value.startswith("http"):
        label = value.rsplit("/", 1)[-1]
        rendered = f'<a href="{html.escape(value, quote=True)}">#{html.escape(label)}</a>'
    else:
        rendered = inline(value)
    return f'<span class="chip"><span class="chip-key">{key}</span>{rendered}</span>'


def layer_map(sections):
    """Assign onion-ring indices to the architecture-layer sections, in document order.

    Any section not in NON_LAYER_SECTIONS is treated as a layer, so an architecture
    profile can name its own middle sections (Domain/Application/... or
    Slice/Persistence/...) without the renderer knowing their names in advance.
    """
    layers = [name for name, _ in sections if name not in NON_LAYER_SECTIONS]
    return {name: idx for idx, name in enumerate(layers)}


def build(meta, sections, template, count=0, branded=True):
    nav, parts = [], []
    layers = layer_map(sections) if KIND == "plan" else {}
    for name, body in sections:
        sid = slug(name)
        layer = layers.get(name) if KIND == "plan" else None
        layer_attr = "" if layer is None else f' data-layer="{layer}"'
        marker = onion_svg(layer, len(layers)) if KIND == "plan" else ""
        nav.append(f'<a href="#{sid}" data-target="{sid}">{html.escape(SHORT.get(name, name))}</a>')
        parts.append(
            f'<section class="plan-section" id="{sid}"{layer_attr}>'
            f'<header class="section-head">{marker}<h2>{html.escape(name)}</h2></header>'
            f'<div class="section-body">{body}</div></section>'
        )
    chip_keys = PLAN_CHIP_KEYS if KIND == "plan" else REVIEW_CHIP_KEYS
    chips = [render_chip(key, meta[key]) for key in chip_keys if meta.get(key)]
    label = "Plan" if KIND == "plan" else "Review"
    title = meta.get("title", "")
    page = template
    for key, value in {
        "KIND": KIND,
        "KINDLABEL": label,
        # The <title> names the artifact in the gallery, where a plan and its review would
        # otherwise share a name; the h1 stays bare because the topbar already shows the kind.
        "PAGETITLE": html.escape(f"{label} - {title}" if title else label),
        "TITLE": html.escape(title or label),
        "TICKET": html.escape(meta.get("ticket", "")),
        "CHIPS": "".join(chips),
        "NAV": "".join(nav),
        "SECTIONS": "\n".join(parts),
        "HINT": PLAN_HINT if KIND == "plan" else REVIEW_HINT,
        "COUNT": str(len(sections)),
        "QUESTIONS": str(count if KIND == "plan" else 0),
        "OPEN": str(count if KIND == "review" else 0),
        "BRAND_STYLE": BRAND_STYLE if branded else "",
        "FOOTER": BRAND_FOOTER if branded else "",
    }.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def main(kind=None, argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="page template (default: assets/page.html)")
    ap.add_argument("--kind", choices=("plan", "review"), default=kind,
                    help="document mode; inferred from the sections and front matter when omitted")
    ap.add_argument("--range", help="review only: git diff range for per-file diffs; default origin/<base>...HEAD, or <sha>^..<sha> when state is merged")
    ap.add_argument("--repo", default=".", help="review only: repository root to run git in (default: current directory)")
    add_profile_arg(ap)
    args = ap.parse_args(argv)
    profile = resolve_profile(explicit=args.profile)
    global SOURCE_DIR, REPO_DIR, DIFF_RANGE
    SOURCE_DIR = Path(args.source).resolve().parent
    REPO_DIR = Path(args.repo).resolve()
    text = Path(args.source).read_text(encoding="utf-8")
    META.clear()
    META.update(parse_meta(text))
    document_kind = args.kind or infer_kind(META, re.findall(r"^## (.+?)\s*$", text, flags=re.M))
    if document_kind == "review":
        DIFF_RANGE = args.range or derive_range(META)
        load_file_stats()
    meta, sections, count = parse(text, document_kind)
    page = build(meta, sections, Path(args.template).read_text(encoding="utf-8"), count,
                 branded=bool(profile.get("branding", True)))
    Path(args.out).write_text(page, encoding="utf-8", newline="\n")
    if document_kind == "plan":
        print(f"wrote {args.out} ({len(page):,} bytes, {len(sections)} sections, {count} answerable questions)")
    else:
        print(f"wrote {args.out} ({len(page):,} bytes, {len(sections)} sections, {count} open findings in the decision form, {len(USED_FILES)} linked file diffs from {DIFF_RANGE})")
    for warning in WARNINGS:
        print("warning: " + warning, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
