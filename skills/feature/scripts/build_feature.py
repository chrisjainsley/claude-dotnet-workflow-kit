#!/usr/bin/env python
"""Render feature.md into the shared HTML page template.

Usage: python build_feature.py plans/<slug>/feature.md --out plans/<slug>/feature.html

Thin wrapper around scripts/render.py in feature mode; --template is optional and
defaults to assets/page.html.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import render  # noqa: E402

if __name__ == "__main__":
    sys.exit(render.main(kind="feature"))
