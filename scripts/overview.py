#!/usr/bin/env python
"""Record a plan's or review's narrated walkthrough as an overview video.

Usage:
  python overview.py plans/<slug>/review.md [--profile <profile.json>] [--range <a>..<b>] [--repo <path>]
  python overview.py plans/<slug>/plan.md

Runs only when the profile's optional.walkthrough is true, after scripts/narrate.py has
recorded the clips. It builds the page into a temporary file beside the source, opens it
in headless Chromium, and records a title card, the page's own walkthrough (scroll,
highlights, captions and the Kokoro clips) and a closing card. The result is
plans/<slug>/overview/<plan|review>.mp4 (1920 x 1080, H.264 and AAC) with a poster
frame beside it; the page builder then adds a Watch overview button that plays it, and
lists both files for publishing. The video is recorded again only when the page source,
the clips or this recorder change.

Needs `pip install playwright` with `python -m playwright install chromium`, and ffmpeg
on PATH. Exit 2 when either is missing, so the caller can carry on without a video.
"""
import argparse
import asyncio
import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_profile import add_profile_arg, resolve_profile  # noqa: E402
from check import split_front_matter  # noqa: E402
import narrate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "scripts" / "render.py"
VIDEO_DIR = "overview"
# The page is laid out as a 1280 x 720 screen and drawn 1.5 times larger: Chromium's
# live capture works in CSS pixels, so a device scale factor would come out at 720p.
VIEW_W, VIEW_H, ZOOM = 1920, 1080, 1.5
CARD_SECONDS = 3.6
END_SECONDS = 4.0
MAX_BYTES = 15 * 1024 * 1024
KIND_LABEL = {"plan": "Plan", "review": "Review"}
CLOSING = {
    "plan": "Answer the open questions and approve the plan on the page.",
    "review": "Make the decision and tick the rollout on the page.",
}
INTRO = {
    "plan": "A narrated tour of the plan, ending on its open questions.",
    "review": "A narrated tour of the review: verdict, changes, findings and rollout.",
}


def video_paths(source):
    folder = source.parent / VIDEO_DIR
    return folder / f"{source.stem}.mp4", folder / f"{source.stem}.jpg", folder / f"{source.stem}.json"


def fingerprint(source):
    """What the video depends on: the document, its clips, the page template and this script."""
    h = hashlib.sha256()
    for path in [source, ROOT / "assets" / "page.html", Path(__file__)]:
        h.update(path.read_bytes())
    manifest = narrate.clip_dir(source) / narrate.MANIFEST
    if manifest.is_file():
        h.update(manifest.read_bytes())
    return h.hexdigest()


def tools_missing():
    missing = []
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        missing.append("playwright (pip install playwright, then python -m playwright install chromium)")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    return missing


def ffconcat(frames, end):
    """Frame list for ffmpeg's concat demuxer: each frame held until the next one arrived."""
    lines = ["ffconcat version 1.0"]
    for i, (name, ts) in enumerate(frames):
        nxt = frames[i + 1][1] if i + 1 < len(frames) else end
        lines += [f"file {name}", f"duration {max(nxt - ts, 0.001):.4f}"]
    lines.append(f"file {frames[-1][0]}")
    return "\n".join(lines) + "\n"


def audio_graph(played, start, total):
    """filter_complex placing each clip at the moment the page started it."""
    parts = []
    for n, (_, t) in enumerate(played):
        parts.append(f"[{n + 1}:a]aresample=48000,adelay={max(0, round((t - start) * 1000))}:all=1[a{n}]")
    fade = max(0.0, total - 0.8)
    if played:
        mix = "".join(f"[a{n}]" for n in range(len(played)))
        parts.append(f"{mix}amix=inputs={len(played)}:normalize=0:dropout_transition=0,apad,"
                     f"atrim=0:{total:.3f},afade=t=out:st={fade:.2f}:d=0.8,pan=stereo|c0=c0|c1=c0[aout]")
    else:
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]")
    parts.append(f"[0:v]fps=30,format=yuv420p,fade=t=in:st=0:d=0.4,fade=t=out:st={fade:.2f}:d=0.8[vout]")
    return ";".join(parts)


CARD_CSS = """
#ov-card { position: fixed; inset: 0; z-index: 9999; display: flex; flex-direction: column; justify-content: center;
  padding: 0 120px; gap: 26px; background: var(--ov-bg); color: #F3F4F6; font-family: var(--sans);
  transition: opacity 0.7s ease; }
#ov-card.hide { opacity: 0; pointer-events: none; }
#ov-card .eyebrow { font: 500 17px/1 var(--mono); letter-spacing: 0.14em; text-transform: uppercase; color: var(--ov-accent); }
#ov-card h1 { margin: 0; font-size: 58px; line-height: 1.08; font-weight: 600; letter-spacing: -0.02em; max-width: 980px; text-wrap: balance; }
#ov-card p { margin: 0; font-size: 24px; line-height: 1.45; color: #9CA3AF; max-width: 860px; }
#ov-card .mark { font: 600 21px var(--sans); color: #F3F4F6; }
#ov-card > * { animation: ov-rise 0.8s cubic-bezier(0.2, 0.7, 0.2, 1) both; }
#ov-card > *:nth-child(2) { animation-delay: 0.12s; } #ov-card > *:nth-child(3) { animation-delay: 0.24s; }
@keyframes ov-rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
.wt-watch { display: none !important; }
"""


def card_html(kind, meta, closing, branded):
    eyebrow = KIND_LABEL[kind] + (f" &middot; {esc(meta.get('ticket', ''))}" if meta.get("ticket") else "")
    if closing:
        mark = '<div class="mark">Delivery Labs &middot; deliverylabs.co/workflow-kit</div>' if branded else ""
        return f'<div class="eyebrow">{eyebrow}</div><h1>{esc(CLOSING[kind])}</h1>{mark}'
    return f'<div class="eyebrow">{eyebrow}</div><h1>{esc(meta.get("title", KIND_LABEL[kind]))}</h1><p>{esc(INTRO[kind])}</p>'


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8", ".mp3": "audio/mpeg", ".wav": "audio/wav"}

    def log_message(self, *args):
        pass


def fetch_via_proxy(url):
    """Web fonts through HTTPS_PROXY: Chromium cannot use a proxy that also takes localhost."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/141 Safari/537.36"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(), response.headers.get("content-type", "application/octet-stream")


async def record(page_url, folder, kind, meta, branded, intro_clip, frames_dir):
    from playwright.async_api import async_playwright
    played, frames = [], []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--hide-scrollbars"])
        context = await browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, color_scheme="light")
        if os.environ.get("HTTPS_PROXY"):
            async def fonts(route):
                try:
                    body, ctype = await asyncio.to_thread(fetch_via_proxy, route.request.url)
                    await route.fulfill(body=body, content_type=ctype)
                except Exception:
                    await route.abort()
            await context.route("https://fonts.googleapis.com/**", fonts)
            await context.route("https://fonts.gstatic.com/**", fonts)
        page = await context.new_page()
        await page.expose_function("__ovPlayed", lambda src, t: played.append((src, t / 1000)))
        await page.add_init_script(f"""
          document.addEventListener('DOMContentLoaded', () => {{ document.documentElement.style.zoom = '{ZOOM}'; }});
          const play = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function () {{ window.__ovPlayed(new URL(this.src).pathname, Date.now()); return play.call(this); }};
        """)
        await page.goto(page_url, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        await page.add_style_tag(content=CARD_CSS)
        await page.evaluate("""([intro, bg, accent]) => {
            const card = document.createElement('div');
            card.id = 'ov-card';
            card.style.setProperty('--ov-bg', bg);
            card.style.setProperty('--ov-accent', accent);
            card.innerHTML = intro;
            document.body.appendChild(card);
        }""", [card_html(kind, meta, False, branded), "#111827" if branded else "#131820", "#A5B4FC" if branded else "#6CC9DE"])
        await page.wait_for_timeout(400)

        cdp = await context.new_cdp_session(page)
        count = [0]

        async def on_frame(event):
            name = f"f{count[0]:06d}.jpg"
            count[0] += 1
            await asyncio.to_thread((frames_dir / name).write_bytes, __import__("base64").b64decode(event["data"]))
            frames.append((name, event["metadata"]["timestamp"]))
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", lambda e: asyncio.ensure_future(on_frame(e)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": VIEW_W,
                                                 "maxHeight": VIEW_H, "everyNthFrame": 1})
        await page.wait_for_timeout(600)
        if intro_clip:
            await page.evaluate("src => new Audio(src).play()", intro_clip)
        await page.wait_for_timeout(int(CARD_SECONDS * 1000))
        await page.evaluate("document.getElementById('ov-card').classList.add('hide')")
        await page.wait_for_timeout(1000)
        await page.click("#wt-play")
        await page.wait_for_function("document.querySelector('.wt-label').textContent === 'Play again'",
                                     timeout=600_000, polling=200)
        await page.wait_for_timeout(1200)
        await page.evaluate("html => { const c = document.getElementById('ov-card'); c.innerHTML = html; c.classList.remove('hide'); }",
                            card_html(kind, meta, True, branded))
        await page.wait_for_timeout(int(END_SECONDS * 1000))
        end = await page.evaluate("Date.now() / 1000")
        await cdp.send("Page.stopScreencast")
        await page.wait_for_timeout(300)
        await browser.close()
    frames.sort(key=lambda f: f[1])
    return frames, played, end


def encode(work, folder, frames, played, end, out_mp4, out_jpg):
    start = frames[0][1]
    total = end - start
    (work / "frames.ffconcat").write_text(ffconcat(frames, end), encoding="utf-8")
    inputs = []
    for src, _ in played:
        inputs += ["-i", str(folder / src.lstrip("/"))]
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "frames.ffconcat", *inputs,
           "-filter_complex", audio_graph(played, start, total), "-map", "[vout]", "-map", "[aout]",
           "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(out_mp4)]
    subprocess.run(cmd, check=True, cwd=work)
    # The poster is the first frame of the walkthrough itself, past the title card.
    poster = next((name for name, ts in frames if ts - start >= CARD_SECONDS + 2.2), frames[-1][0])
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(work / poster), "-vf", "scale=1280:-2",
                    "-q:v", "4", str(out_jpg)], check=True)
    return total


def intro_line(source, kind, meta):
    """The title card's spoken line, recorded with the walkthrough's voice; None without Kokoro."""
    synth = narrate.kokoro_engine(narrate.model_dir(None))
    if synth is None:
        return None
    text = f"{KIND_LABEL[kind]}: {meta.get('title', '').strip()}." if meta.get("title") else f"{KIND_LABEL[kind]}."
    path = source.parent / VIDEO_DIR / f"{source.stem}-intro-{narrate.clip_name(text)}.mp3"
    for old in path.parent.glob(f"{source.stem}-intro-*"):
        if old.name != path.name:
            old.unlink()
    if not path.is_file():
        samples, rate = synth(text)
        data, ext = narrate.encode(narrate.wav_bytes(samples, rate), True)
        path = path.with_suffix(ext)
        path.write_bytes(data)
    return path.relative_to(source.parent).as_posix()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("--range", help="review only: passed to the page builder")
    ap.add_argument("--repo", help="review only: passed to the page builder")
    ap.add_argument("--force", action="store_true", help="record even when nothing changed")
    add_profile_arg(ap)
    args = ap.parse_args(argv)
    profile = resolve_profile(explicit=args.profile)
    if not profile.get("optional", {}).get("walkthrough", False):
        print("skipped: optional.walkthrough is false in the profile")
        return 0
    source = Path(args.source).resolve()
    if not narrate.sentences_of(source):
        print(f"{source.name} has no Walkthrough; no overview video")
        return 0
    missing = tools_missing()
    if missing:
        print("skipped: the overview video needs " + " and ".join(missing))
        return 2
    out_mp4, out_jpg, stamp = video_paths(source)
    current = fingerprint(source)
    if not args.force and out_mp4.is_file() and stamp.is_file() and json.loads(stamp.read_text()).get("fingerprint") == current:
        print(f"overview: unchanged ({out_mp4})")
        return 0
    meta, _ = split_front_matter(source.read_text(encoding="utf-8"))
    kind = "plan" if source.stem == "plan" else "review"
    out_mp4.parent.mkdir(exist_ok=True)
    intro = intro_line(source, kind, meta)
    folder = source.parent
    page = folder / f".{source.stem}.overview.html"
    build = [sys.executable, str(RENDER), str(source), "--out", str(page), "--kind", kind]
    for flag in ("range", "repo", "profile"):
        if getattr(args, flag):
            build += [f"--{flag}", getattr(args, flag)]
    manifest = folder / f"{kind}.files.json"
    kept_manifest = manifest.read_bytes() if manifest.is_file() else None
    try:
        subprocess.run(build, check=True, capture_output=True, text=True)
        handler = functools.partial(QuietHandler, directory=str(folder))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/{page.name}"
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            frames, played, end = asyncio.run(record(url, folder, kind, meta, bool(profile.get("branding", True)), intro, work))
            server.shutdown()
            if not frames:
                print("overview: no frames were captured")
                return 1
            total = encode(work, folder, frames, played, end, out_mp4, out_jpg)
    finally:
        # The temporary build rewrote the files list; put back what the real build left.
        page.unlink(missing_ok=True)
        if kept_manifest is not None:
            manifest.write_bytes(kept_manifest)
        else:
            manifest.unlink(missing_ok=True)
    size = out_mp4.stat().st_size
    stamp.write_text(json.dumps({"fingerprint": current, "seconds": round(total, 1)}) + "\n", encoding="utf-8")
    print(f"overview: {out_mp4} ({total:.0f} s, {size / 1048576:.1f} MB, {len(played)} clips)")
    if size > MAX_BYTES:
        print(f"warning: {out_mp4.name} is over 15 MB, the Artifact file limit; shorten the walkthrough")
    return 0


if __name__ == "__main__":
    sys.exit(main())
