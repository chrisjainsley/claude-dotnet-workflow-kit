#!/usr/bin/env python
"""Render plan.md into the skill's HTML template.

Usage: python build_plan.py plans/<slug>/plan.md --template <template.html> --out plans/<slug>/plan.html

The markdown subset is deliberately small: ## sections, ### subheads, paragraphs,
bullet and numbered lists (one nesting level), pipe tables, fenced code
(```mermaid becomes a native mermaid block), inline code, bold, italic, links.
HTML comments in the source are dropped so skeleton hints never reach the page.

Images (`![caption](context/frame.png)`, path relative to plan.md) are inlined as data
URIs, downscaled to 1600px wide when Pillow is installed, and consecutive images form a
grid. The "Context" section renders collapsed inside a <details> element.

The "Open questions" section is special: each numbered item becomes a question,
nested "- [x] **Label.** detail" / "- [ ] ..." lines become radio options ([x] is
the recommended, preselected one), and a question with no options becomes a
free-text answer. Question ids derive from the title text, so a republish keeps
answers already stored as long as the title is unchanged.
"""
import argparse
import base64
import html
import io
import mimetypes
import re
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # Pillow is optional; images are inlined at their original size without it
    Image = None

SOURCE_DIR = Path(".")
MAX_IMAGE_WIDTH = 1600

LAYER_OF = {
    "Requirement": 0, "Specs": 0, "Domain": 1, "Application": 2,
    "Infrastructure": 3, "API": 4,
}
SHORT = {
    "Risks and rollout": "Risks", "Open questions": "Questions",
}
LANG_ALIAS = {"cs": "csharp", "c#": "csharp", "gql": "graphql", "feature": "gherkin", "sh": "bash", "ps1": "powershell"}
QUESTIONS_SECTION = "Open questions"
CONTEXT_SECTION = "Context"
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")


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


def image_data_uri(path):
    file = (SOURCE_DIR / path).resolve()
    if not file.exists():
        return None
    data = file.read_bytes()
    mime = mimetypes.guess_type(file.name)[0] or "image/png"
    if Image is not None and mime in ("image/png", "image/jpeg", "image/webp"):
        with Image.open(io.BytesIO(data)) as img:
            if img.width > MAX_IMAGE_WIDTH:
                ratio = MAX_IMAGE_WIDTH / img.width
                img = img.resize((MAX_IMAGE_WIDTH, round(img.height * ratio)))
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


def render_table(lines):
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
    rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    out = ['<div class="table-wrap"><table><thead><tr>']
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table></div>")
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


LIST_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")


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
        indent = len(m.group(1))
        if indent == 0:
            items.append([m.group(3), []])
        elif items:
            items[-1][1].append([m.group(3), []])
        i += 1
    return items, i


def render_blocks(lines):
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            lang = LANG_ALIAS.get(line[3:].strip().lower(), line[3:].strip().lower())
            code, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            body = html.escape("\n".join(code), quote=False)
            if lang == "mermaid":
                out.append(f'<pre class="mermaid">{body}</pre>')
            else:
                cls = f' class="language-{lang}"' if lang else ""
                out.append(f"<pre><code{cls}>{body}</code></pre>")
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
            out.append(render_table(table))
            continue
        if LIST_RE.match(line):
            ordered = LIST_RE.match(line).group(2)[0].isdigit()
            items, i = parse_list(lines, i)
            out.append(render_list(items, ordered))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(```|### |\s*[-*]\s|\s*\d+\.\s|\s*\||!\[)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
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
            for k, (opt_text, _) in enumerate(options, start=1):
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


def parse(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        for line in text[3:end].strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[end + 4:]
    sections, current = [], None
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            current = [m.group(1).strip(), []]
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    rendered = []
    for name, lines in sections:
        if name == QUESTIONS_SECTION:
            body, count = render_questions(lines)
            rendered.append((name, body, count))
        elif name == CONTEXT_SECTION:
            body = render_blocks(lines)
            rendered.append((name, f'<details class="context"><summary>Parent feature, area and designs</summary>{body}</details>', 0))
        else:
            rendered.append((name, render_blocks(lines), 0))
    return meta, rendered


def onion_svg(active):
    rings = []
    for idx in range(5):
        r = 6 + idx * 6
        cls = "ring active" if active == idx else "ring"
        rings.append(f'<circle class="{cls}" cx="32" cy="32" r="{r}"/>')
    return '<svg class="onion" viewBox="0 0 64 64" aria-hidden="true">' + "".join(rings) + "</svg>"


def build(meta, sections, template):
    nav, parts = [], []
    for name, body, _ in sections:
        sid = slug(name)
        layer = LAYER_OF.get(name)
        layer_attr = "" if layer is None else f' data-layer="{layer}"'
        nav.append(f'<a href="#{sid}" data-target="{sid}">{html.escape(SHORT.get(name, name))}</a>')
        parts.append(
            f'<section class="plan-section" id="{sid}"{layer_attr}>'
            f'<header class="section-head">{onion_svg(layer)}<h2>{html.escape(name)}</h2></header>'
            f'<div class="section-body">{body}</div></section>'
        )
    chips = []
    for key in ("ticket", "branch", "base", "size", "date"):
        if meta.get(key):
            chips.append(f'<span class="chip"><span class="chip-key">{key}</span>{inline(meta[key])}</span>')
    question_count = sum(c for _, _, c in sections)
    page = template
    for key, value in {
        "TITLE": html.escape(meta.get("title", "Plan")),
        "TICKET": html.escape(meta.get("ticket", "")),
        "CHIPS": "".join(chips),
        "NAV": "".join(nav),
        "SECTIONS": "\n".join(parts),
        "COUNT": str(len(sections)),
        "QUESTIONS": str(question_count),
    }.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    global SOURCE_DIR
    SOURCE_DIR = Path(args.source).resolve().parent
    meta, sections = parse(Path(args.source).read_text(encoding="utf-8"))
    page = build(meta, sections, Path(args.template).read_text(encoding="utf-8"))
    Path(args.out).write_text(page, encoding="utf-8", newline="\n")
    questions = sum(c for _, _, c in sections)
    print(f"wrote {args.out} ({len(page):,} bytes, {len(sections)} sections, {questions} answerable questions)")


if __name__ == "__main__":
    main()
