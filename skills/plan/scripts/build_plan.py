#!/usr/bin/env python
"""Render plan.md into the shared HTML page template.

Usage: python build_plan.py plans/<slug>/plan.md --out plans/<slug>/plan.html

Thin wrapper around scripts/render.py in plan mode; --template is optional and
defaults to assets/page.html.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import render  # noqa: E402

if __name__ == "__main__":
    sys.exit(render.main(kind="plan"))
