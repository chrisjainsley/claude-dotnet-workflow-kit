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
form a grid. A `.dc.html` target (an artboard read from a Design canvas) is embedded
instead as a sandboxed iframe at the artboard's own size, scaled to the column by the
page script and opened full size by the diagram dialog; its `support.js` line is
dropped because the canvas runtime is not present, so only static artboards render
faithfully.

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
(derived from the front matter when omitted), QA report renders scenario cards whose
gherkin steps expand to the evidence captioned with their text,
Rollout renders a persistent checklist, and Decision gets the approve /
request-changes form.
"""
import argparse
import base64
import hashlib
import html
import io
import json
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
from check import STEP_RE, is_video, step_key  # noqa: E402

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
MAX_DESIGN_BYTES = 2 * 1024 * 1024
DESIGN_DEFAULT_SIZE = (1280, 800)
SUPPORT_JS_RE = re.compile(r"[ \t]*<script[^>]*support\.js[^>]*>\s*</script>[ \t]*(?:\r?\n)?", re.I)
PREVIEW_RE = re.compile(r'"\$preview"\s*:\s*\{([^}]*)\}')
MAX_FILE_DIFF_LINES = 400
SECRET_PATTERNS = re.compile(
    r"(appsettings[^/]*\.json|local\.settings\.json|\.tfvars|(^|/)\.env(\.[^/]*)?|secrets?\.(json|ya?ml)"
    r"|\.pfx|\.pem|\.p12|\.key|(^|/)id_(rsa|dsa|ecdsa|ed25519)|(^|/)\.npmrc|(^|/)\.pypirc|(^|/)credentials(\.[^/]*)?)$",
    re.I,
)
META = {}
DIFF_RANGE = None
FILE_STATS = {}
USED_FILES = []
WARNINGS = []
MEDIA_FILES = []
HTTP_STATUS_RE = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})\b")
HEADER_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+:\s")

NON_LAYER_SECTIONS = {
    "Context", "Requirement", "Specs", "Designs", "Tests", "Decisions",
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
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s\x22]+)\)", r'<a href="\2">\1</a>', text)
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


def is_design(path):
    return path.lower().endswith(".dc.html")


def design_size(source):
    """The artboard's $preview width and height, else the default desktop frame."""
    m = PREVIEW_RE.search(source)
    if m:
        w = re.search(r'"width"\s*:\s*(\d+)', m.group(1))
        h = re.search(r'"height"\s*:\s*(\d+)', m.group(1))
        if w and h:
            return int(w.group(1)), int(h.group(1))
    return DESIGN_DEFAULT_SIZE


def render_design(alt, path):
    file = (SOURCE_DIR / path).resolve()
    try:
        source = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return f'<div class="figures"><figure class="missing"><figcaption>Missing artboard: {html.escape(path)}</figcaption></figure></div>'
    if len(source.encode("utf-8")) > MAX_DESIGN_BYTES:
        WARNINGS.append(f"artboard {path} is over {MAX_DESIGN_BYTES // (1024 * 1024)} MB; the page must stay under 16 MB")
    source = SUPPORT_JS_RE.sub("", source)
    width, height = design_size(source)
    caption = html.escape(alt, quote=True)
    return (
        f'<figure class="design"><div class="design-frame">'
        f'<iframe sandbox="" srcdoc="{html.escape(source, quote=True)}" title="{caption}" '
        f'width="{width}" height="{height}" loading="lazy"></iframe></div>'
        f'<figcaption><span>{inline(alt)}</span>'
        f'<button type="button" class="diagram-open">Open full size</button></figcaption></figure>'
    )


def render_figures(lines):
    out = []
    grid = []
    for line in lines:
        alt, path = IMAGE_RE.match(line.strip()).groups()
        if is_design(path):
            if grid:
                out.append(render_image_grid(grid))
                grid = []
            out.append(render_design(alt, path))
        else:
            grid.append((alt, path))
    if grid:
        out.append(render_image_grid(grid))
    return "".join(out)


def render_image_grid(figures):
    out = ['<div class="figures">']
    for alt, path in figures:
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


def fence_info(line):
    """(lang, caption) from a fence opener: the first word is the language, the rest a caption."""
    info = line.strip()[3:].strip().split(None, 1)
    lang = info[0].lower() if info else ""
    return LANG_ALIAS.get(lang, lang), (info[1].strip() if len(info) > 1 else "")


def read_fence(lines, i, with_caption=False):
    lang, caption = fence_info(lines[i])
    code, i = [], i + 1
    while i < len(lines) and not lines[i].startswith("```"):
        code.append(lines[i])
        i += 1
    if with_caption:
        return lang, caption, "\n".join(code), i + 1
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
    cls = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
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
            if para and mode == "qa" and re.match(r"^(Evidence|Classification|Not covered):", lines[i]):
                break
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


def pretty_json(text):
    """A JSON body indented for reading; anything that does not parse stays as it was."""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def http_part(lines):
    """Start line and headers, then the body pretty-printed when it is JSON."""
    cut = 1
    while cut < len(lines) and HEADER_RE.match(lines[cut]):
        cut += 1
    head, body = lines[:cut], lines[cut:]
    text = "\n".join(head)
    body_text = "\n".join(body).strip()
    if body_text:
        text += "\n\n" + pretty_json(body_text)
    return text


def render_http(body):
    """An http fence as a request pane and a response pane, split at the first status
    line. Without one the fence renders as a plain http block."""
    lines = body.splitlines()
    at = next((n for n, l in enumerate(lines) if HTTP_STATUS_RE.match(l)), None)
    if at is None:
        return f'<div class="evidence-item"><span class="qa-label">http</span>{render_code("http", body)}</div>'
    request, response = lines[:at], lines[at:]
    while request and not request[-1].strip():
        request.pop()
    status = int(HTTP_STATUS_RE.match(response[0]).group(1))
    tone = "pass" if status < 300 else "fail" if status >= 400 else "info"
    start = next((l.strip() for l in request if l.strip()), "")
    return (
        '<div class="evidence-item http-pair">'
        f'<div class="http-pane"><div class="http-head"><span class="qa-label">Request</span>'
        f'<code class="http-line">{html.escape(start)}</code></div>{render_code("http", http_part(request))}</div>'
        f'<div class="http-pane"><div class="http-head"><span class="qa-label">Response</span>'
        f'<span class="pill pill-{tone}">{status}</span></div>{render_code("http", http_part(response))}</div>'
        "</div>"
    )


def render_evidence(item):
    kind, caption, payload = item
    if kind in ("image", "video"):
        return render_media_grid([item])
    if kind == "http":
        return render_http(payload)
    return f'<div class="evidence-item"><span class="qa-label">{html.escape(kind)}</span>{render_code(kind, payload)}</div>'


def media_caption(caption):
    m = STEP_RE.match(caption)
    if not m:
        return inline(caption)
    keyword = caption.strip()[:len(m.group(1))]
    return f'<span class="kw">{html.escape(keyword)}</span> {inline(caption.strip()[len(keyword):].strip())}'


def render_media_grid(items):
    """QA screenshots and videos as one visible grid. The files are referenced by their
    relative path and published next to the page, never inlined: a video cannot be."""
    out = ['<div class="figures qa-media">']
    for kind, caption, path in items:
        if not (SOURCE_DIR / path).is_file():
            out.append(f'<figure class="missing"><figcaption>Missing {kind}: {html.escape(path)}</figcaption></figure>')
            continue
        if path not in MEDIA_FILES:
            MEDIA_FILES.append(path)
        src, alt = html.escape(path, quote=True), html.escape(caption, quote=True)
        if kind == "video":
            media = f'<video controls preload="metadata" playsinline src="{src}" aria-label="{alt}"></video>'
            out.append(f'<figure class="video">{media}<figcaption>{media_caption(caption)}</figcaption></figure>')
        else:
            out.append(f'<figure class="shot"><img src="{src}" alt="{alt}" loading="lazy"><figcaption>{media_caption(caption)}</figcaption></figure>')
    out.append("</div>")
    return "".join(out)


def render_steps(body, items, scenario):
    """The scenario's gherkin as a step list. A step whose text a fence caption repeats
    becomes a collapsed item holding that evidence; the rest stay plain lines. Screenshots
    and videos, captioned with a step or the scenario title, show in one grid below."""
    lines = body.splitlines()
    steps = {step_key(l) for l in lines if STEP_RE.match(l)}
    by_step, unmatched, media = {}, [], []
    for item in items:
        key = step_key(item[1])
        if item[0] in ("image", "video") and (key in steps or key == step_key(scenario)):
            media.append(item)
        elif key in steps:
            by_step.setdefault(key, []).append(item)
        else:
            unmatched.append(item)
    out = ['<div class="steps">']
    for line in lines:
        if not line.strip():
            continue
        m = STEP_RE.match(line)
        if not m:
            out.append(f'<div class="step-other">{html.escape(line.strip())}</div>')
            continue
        keyword = line.strip()[:len(m.group(1))]
        head = f'<span class="kw">{html.escape(keyword)}</span> {html.escape(line.strip()[len(keyword):].strip())}'
        evidence = by_step.pop(step_key(line), None)
        if evidence:
            count = f'{len(evidence)} item{"s" if len(evidence) > 1 else ""}'
            out.append(f'<details class="step"><summary><span>{head}</span><span class="ev-count">{count}</span></summary>'
                       f'{"".join(render_evidence(e) for e in evidence)}</details>')
        else:
            out.append(f'<div class="step">{head}</div>')
    out.append("</div>")
    if media:
        out.append(render_media_grid(media))
    for item in unmatched:
        WARNINGS.append(f"QA report: evidence '{item[1] or item[0]}' under '{scenario}' names no step; shown after the steps")
        out.append(f'<details class="hunk evidence"><summary>{inline(item[1] or item[0])}</summary>{render_evidence(item)}</details>')
    return "".join(out)


def render_scenario(lines):
    """One '#### ' scenario block: evidence fences and images after the gherkin are lifted
    out of the flow and folded into the steps they name."""
    title = lines[0][5:].strip()
    gherkin, items, before, after, i = None, [], [], [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            start = i
            lang, caption, body, i = read_fence(lines, i, with_caption=True)
            if lang == "gherkin" and gherkin is None:
                gherkin = body
            elif gherkin is not None:
                items.append((lang, caption, body))
            else:
                before.extend(lines[start:i])
            continue
        if gherkin is not None and IMAGE_RE.match(line.strip()):
            alt, path = IMAGE_RE.match(line.strip()).groups()
            items.append(("video" if is_video(path) else "image", alt, path))
        else:
            (after if gherkin is not None else before).append(line)
        i += 1
    if gherkin is None:
        return render_blocks(lines, "qa")
    name = re.sub(r"\s*`.*$", "", title)
    return render_blocks(before, "qa") + render_steps(gherkin, items, name) + render_blocks(after, "qa")


def render_qa(lines):
    """QA report: split at '#### ' scenario headings (outside fences) and render each."""
    segments, current, in_fence = [], [], False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        if line.startswith("#### ") and not in_fence and current:
            segments.append(current)
            current = []
        current.append(line)
    if current:
        segments.append(current)
    return "\n".join(render_scenario(s) if s[0].startswith("#### ") else render_blocks(s, "qa") for s in segments)


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
        if mode == "qa":
            body = render_qa(lines)
        else:
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
    MEDIA_FILES.clear()
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
        # Evidence media is referenced by relative path, so it is published beside the
        # page: the list below is the Artifact tool's `files` argument, with root = the
        # review's folder.
        out_dir = Path(args.out).resolve().parent
        manifest = out_dir / "review.files.json"
        manifest.write_text(json.dumps(sorted(MEDIA_FILES), indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"evidence files: {len(MEDIA_FILES)} ({manifest.name})")
        if MEDIA_FILES and out_dir != SOURCE_DIR:
            WARNINGS.append(f"--out is not beside {Path(args.source).name}; the page's evidence/ paths will not resolve until the files sit next to it")
    for warning in WARNINGS:
        print("warning: " + warning, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
