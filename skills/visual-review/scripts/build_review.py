#!/usr/bin/env python
"""Render review.md into the shared HTML page template.

Usage: python build_review.py plans/<slug>/review.md --out plans/<slug>/review.html

Thin wrapper around scripts/render.py in review mode; --template is optional and
defaults to assets/page.html. --range and --repo control the git-backed per-file
diffs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import render  # noqa: E402

if __name__ == "__main__":
    sys.exit(render.main(kind="review"))
