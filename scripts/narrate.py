#!/usr/bin/env python
"""Record a plan's or review's Walkthrough with Kokoro, an open-source voice model run locally.

Usage:
  python narrate.py plans/<slug>/review.md [--profile <profile.json>]
  python narrate.py plans/<slug>/plan.md

Runs only when the profile's optional.walkthrough is true. Every page uses the same
voice, Kokoro's af_heart. Each spoken sentence becomes one clip under
plans/<slug>/walkthrough/<plan|review>/, named by a hash of the voice and text, so a
rebuild only records the sentences that changed and deletes clips no sentence uses any
more. narration.json in that folder maps each sentence to its clip; the page builder
reads it, attaches each clip to its sentence and lists the clips in plan.files.json or
review.files.json so they publish next to the page.

Needs `pip install kokoro-onnx` (onnxruntime, no PyTorch). The model (88 MB) and the
voice pack (28 MB) download once from the kokoro-onnx GitHub release into --model-dir
(default ~/.cache/dotnet-workflow-kit/kokoro, or KIT_KOKORO_DIR). Clips are MP3 when
ffmpeg is on PATH, WAV otherwise. Nothing is sent anywhere: the text never leaves the
machine. Exit 2 when Kokoro is not installed; the page then shows the captions without
sound.
"""
import argparse
import array
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_profile import add_profile_arg, resolve_profile  # noqa: E402
from check import WALKTHROUGH, spoken_sentences, split_front_matter, split_sections, walkthrough_scenes  # noqa: E402

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
VOICE = "af_heart"
SPEED = 1.0
CLIP_DIR = "walkthrough"
MANIFEST = "narration.json"


def model_dir(explicit):
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("KIT_KOKORO_DIR"):
        return Path(os.environ["KIT_KOKORO_DIR"]).expanduser()
    return Path.home() / ".cache" / "dotnet-workflow-kit" / "kokoro"


def fetch_model(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        target = folder / name
        if target.is_file() and target.stat().st_size > 0:
            continue
        print(f"downloading {name} to {folder} (once)")
        partial = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(RELEASE + name) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(target)
    return [folder / name for name in MODEL_FILES]


def kokoro_engine(folder, voice=VOICE, speed=SPEED):
    """A function text -> (float samples, sample rate), or None when Kokoro is missing."""
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        return None
    model, voices = fetch_model(folder)
    kokoro = Kokoro(str(model), str(voices))
    return lambda text: kokoro.create(text, voice=voice, speed=speed, lang="en-us")


def wav_bytes(samples, rate):
    """16-bit mono WAV from float samples in -1..1, with the standard library only."""
    pcm = array.array("h", (round(max(-1.0, min(1.0, float(v))) * 32767) for v in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    pcm = pcm.tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buffer.getvalue()


def encode(wav, mp3):
    """(bytes, extension): MP3 through ffmpeg when it is there, the WAV as it is otherwise."""
    if not mp3:
        return wav, ".wav"
    done = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", "-ac", "1",
                           "-b:a", "48k", "-f", "mp3", "pipe:1"], input=wav, capture_output=True, check=True)
    return done.stdout, ".mp3"


def clip_dir(source):
    """walkthrough/<plan|review>/ beside the source: a plan and its review share a folder,
    and each recording deletes the clips its own document no longer uses."""
    return source.parent / CLIP_DIR / source.stem


def clip_name(text, voice=VOICE, speed=SPEED):
    return hashlib.sha256(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()[:16]


def sentences_of(source):
    meta, body = split_front_matter(source.read_text(encoding="utf-8"))
    sections = dict(split_sections(body))
    if WALKTHROUGH not in sections:
        return []
    scenes, _ = walkthrough_scenes(sections[WALKTHROUGH])
    return [s for _, text in scenes for s in spoken_sentences(text)]


def narrate(source, synth, mp3=True, voice=VOICE, speed=SPEED):
    """Record every Walkthrough sentence that has no clip yet, drop clips no sentence
    uses, and write the manifest. Returns (recorded, kept, removed)."""
    out_dir = clip_dir(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = ".mp3" if mp3 else ".wav"
    clips, recorded, kept = [], 0, 0
    for text in dict.fromkeys(sentences_of(source)):
        name = clip_name(text, voice, speed)
        existing = next((p for p in (out_dir / (name + ".mp3"), out_dir / (name + ".wav")) if p.is_file()), None)
        if existing is None:
            samples, rate = synth(text)
            data, ext = encode(wav_bytes(samples, rate), mp3)
            existing = out_dir / (name + ext)
            existing.write_bytes(data)
            recorded += 1
        else:
            kept += 1
        clips.append({"text": text, "file": existing.relative_to(source.parent).as_posix()})
    used = {Path(c["file"]).name for c in clips}
    removed = 0
    for old in out_dir.iterdir():
        if old.suffix in (".mp3", ".wav") and old.name not in used:
            old.unlink()
            removed += 1
    manifest = {"engine": "kokoro", "voice": voice, "speed": speed, "clips": clips}
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return recorded, kept, removed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("--model-dir", help="where the model files live (default ~/.cache/dotnet-workflow-kit/kokoro)")
    add_profile_arg(ap)
    args = ap.parse_args(argv)
    if not resolve_profile(explicit=args.profile).get("optional", {}).get("walkthrough", False):
        print("skipped: optional.walkthrough is false in the profile")
        return 0
    source = Path(args.source)
    if not sentences_of(source):
        print(f"{source.name} has no Walkthrough; nothing to record")
        return 0
    synth = kokoro_engine(model_dir(args.model_dir))
    if synth is None:
        print("skipped: Kokoro is not installed (pip install kokoro-onnx); the page will show captions without sound")
        return 2
    recorded, kept, removed = narrate(source, synth, mp3=shutil.which("ffmpeg") is not None)
    print(f"narration: {recorded} recorded, {kept} unchanged, {removed} removed "
          f"({clip_dir(source) / MANIFEST})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
