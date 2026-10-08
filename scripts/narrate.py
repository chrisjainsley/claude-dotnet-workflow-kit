#!/usr/bin/env python
"""Record the review's Walkthrough with Kokoro, an open-source voice model run locally.

Usage:
  python narrate.py plans/<slug>/review.md [--voice af_heart] [--speed 1.0]

Each spoken sentence becomes one clip under plans/<slug>/walkthrough/, named by a hash
of the voice, speed and text, so a rebuild only records the sentences that changed and
deletes clips no sentence uses any more. walkthrough/narration.json maps each sentence
to its clip; the page builder reads it, plays the clips in place of the browser's voice
and lists them in review.files.json so they publish next to the page.

Needs `pip install kokoro-onnx` (onnxruntime, no PyTorch). The model (88 MB) and the
voice pack (28 MB) download once from the kokoro-onnx GitHub release into --model-dir
(default ~/.cache/dotnet-workflow-kit/kokoro, or KIT_KOKORO_DIR). Clips are MP3 when
ffmpeg is on PATH, WAV otherwise. Nothing is sent anywhere: the text never leaves the
machine. Exit 2 when Kokoro is not installed, so the caller can fall back to the
browser voice.

Voices: af_heart (default, the best graded), af_bella, am_michael; British bf_emma,
bf_isabella, bm_george, bm_fable.
"""
import argparse
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
from check import WALKTHROUGH, spoken_sentences, split_front_matter, split_sections, walkthrough_scenes  # noqa: E402

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
DEFAULT_VOICE = "af_heart"
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


def kokoro_engine(folder, voice, speed):
    """A function text -> (float samples, sample rate), or None when Kokoro is missing."""
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        return None
    model, voices = fetch_model(folder)
    kokoro = Kokoro(str(model), str(voices))
    if voice not in kokoro.get_voices():
        raise SystemExit(f"unknown voice '{voice}'; try one of: {', '.join(sorted(kokoro.get_voices()))}")
    lang = "en-gb" if voice[:1] == "b" else "en-us"
    return lambda text: kokoro.create(text, voice=voice, speed=speed, lang=lang)


def wav_bytes(samples, rate):
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
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


def clip_name(voice, speed, text):
    return hashlib.sha256(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()[:16]


def sentences_of(source):
    meta, body = split_front_matter(source.read_text(encoding="utf-8"))
    sections = dict(split_sections(body))
    if WALKTHROUGH not in sections:
        return []
    scenes, _ = walkthrough_scenes(sections[WALKTHROUGH])
    return [s for _, text in scenes for s in spoken_sentences(text)]


def narrate(source, synth, voice, speed=1.0, mp3=True):
    """Record every Walkthrough sentence that has no clip yet, drop clips no sentence
    uses, and write the manifest. Returns (recorded, kept, removed)."""
    out_dir = source.parent / CLIP_DIR
    out_dir.mkdir(exist_ok=True)
    ext = ".mp3" if mp3 else ".wav"
    clips, recorded, kept = [], 0, 0
    for text in dict.fromkeys(sentences_of(source)):
        name = clip_name(voice, speed, text)
        existing = next((p for p in (out_dir / (name + ".mp3"), out_dir / (name + ".wav")) if p.is_file()), None)
        if existing is None:
            samples, rate = synth(text)
            data, ext = encode(wav_bytes(samples, rate), mp3)
            existing = out_dir / (name + ext)
            existing.write_bytes(data)
            recorded += 1
        else:
            kept += 1
        clips.append({"text": text, "file": f"{CLIP_DIR}/{existing.name}"})
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
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"Kokoro voice id (default {DEFAULT_VOICE})")
    ap.add_argument("--speed", type=float, default=1.0, help="speaking rate, 1.0 is natural")
    ap.add_argument("--model-dir", help="where the model files live (default ~/.cache/dotnet-workflow-kit/kokoro)")
    args = ap.parse_args(argv)
    source = Path(args.source)
    if not sentences_of(source):
        print(f"{source.name} has no Walkthrough; nothing to record")
        return 0
    synth = kokoro_engine(model_dir(args.model_dir), args.voice, args.speed)
    if synth is None:
        print("skipped: Kokoro is not installed (pip install kokoro-onnx); the page will use the browser voice")
        return 2
    recorded, kept, removed = narrate(source, synth, args.voice, args.speed, mp3=shutil.which("ffmpeg") is not None)
    print(f"narration: {recorded} recorded, {kept} unchanged, {removed} removed, voice {args.voice} "
          f"({source.parent / CLIP_DIR / MANIFEST})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
