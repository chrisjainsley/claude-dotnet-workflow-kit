#!/usr/bin/env python
"""Fail loudly when a plan.md breaks the section skeleton or its word budget.

Usage: python check_plan.py plans/<slug>/plan.md [--profile <profile.json>]

Thin wrapper around scripts/check.py in plan mode.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check  # noqa: E402

if __name__ == "__main__":
    sys.exit(check.main(kind="plan"))
