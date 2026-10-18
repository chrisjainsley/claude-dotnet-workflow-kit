#!/usr/bin/env python
"""Fail loudly when a feature.md breaks the section skeleton or its word budget.

Usage: python check_feature.py plans/<slug>/feature.md [--profile <profile.json>]

Thin wrapper around scripts/check.py in feature mode.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check  # noqa: E402

if __name__ == "__main__":
    sys.exit(check.main(kind="feature"))
