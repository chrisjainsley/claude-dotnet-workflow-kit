import re
from pathlib import Path

from conftest import REPO_ROOT

BANNED_SUBSTRINGS = (
    "blue steel",
    "realvision",
    "dev.azure.com/realvisionplatform",
    "chris.ainsley",
    r"c:\users",
    "rv2",
)

ALLOWED_CHRIS_FILES = {
    (REPO_ROOT / "README.md").resolve(),
    (REPO_ROOT / "LICENSE").resolve(),
    (REPO_ROOT / ".claude-plugin" / "plugin.json").resolve(),
    (REPO_ROOT / ".claude-plugin" / "marketplace.json").resolve(),
}

SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
BINARY_SUFFIXES = {
    ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".zip", ".pdf", ".mp4", ".mp3",
}
THIS_FILE = Path(__file__).resolve()
CHRIS_RE = re.compile(r"\bChris\b")


def iter_text_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved == THIS_FILE:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        yield path


def read_text_or_none(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        return None


def test_given_all_files_then_no_private_strings():
    offenses = []
    for path in iter_text_files():
        text = read_text_or_none(path)
        if text is None:
            continue
        resolved = path.resolve()
        for lineno, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for needle in BANNED_SUBSTRINGS:
                if needle in lower:
                    offenses.append(f"{path}:{lineno}: banned string '{needle}' -> {line.strip()[:160]}")
            if resolved not in ALLOWED_CHRIS_FILES and CHRIS_RE.search(line):
                offenses.append(f"{path}:{lineno}: contains 'Chris' -> {line.strip()[:160]}")
    assert offenses == [], "private/leaked strings found:\n" + "\n".join(offenses)


def test_given_any_markdown_then_no_em_dash():
    offenses = []
    for path in REPO_ROOT.rglob("*.md"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        text = read_text_or_none(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "\u2014" in line:
                offenses.append(f"{path}:{lineno}: em dash -> {line.strip()[:160]}")
    assert offenses == [], "em dashes found in markdown:\n" + "\n".join(offenses)
