import re

import pytest

import profile as profile_mod
from conftest import ADAPTERS_DIR, REPO_ROOT

DOCS_ADAPTERS = REPO_ROOT / "docs" / "adapters.md"

_HAS_ADAPTER_FILES = ADAPTERS_DIR.exists() and any(ADAPTERS_DIR.rglob("*.md"))

pytestmark = pytest.mark.skipif(
    not _HAS_ADAPTER_FILES,
    reason="adapters/ has no adapter files yet (written by a parallel agent)",
)

BOLD_ITEM_RE = re.compile(r"^-\s+\*\*(.+?)\*\*", re.M)
LOCAL_RUN_MARKER = "is not about naming or contracts"


def concern_dir(dotted):
    if dotted == "qa.owner":
        return ADAPTERS_DIR / "qa"
    if dotted.startswith("stack."):
        return ADAPTERS_DIR / "stack" / dotted.split(".", 1)[1]
    return ADAPTERS_DIR / dotted


def adapter_cases():
    cases = []
    for dotted, values in profile_mod.ENUMS.items():
        if dotted not in ("architecture", "tracker", "scm", "qa.owner") and not dotted.startswith("stack."):
            continue
        for value in values:
            cases.append((dotted, value))
    return cases


def parse_concern_blocks():
    """docs/adapters.md documents each concern under its own '### <concern>' heading."""
    if not DOCS_ADAPTERS.exists():
        return None
    text = DOCS_ADAPTERS.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^### (.+)$", text))
    blocks = {}
    for i, match in enumerate(matches):
        name = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks[name] = text[start:end]
    return blocks


def required_headings(dotted, blocks):
    """The bold list-item labels docs/adapters.md requires as '## ' headings for this concern."""
    if blocks is None:
        return None
    if dotted in ("architecture", "tracker", "scm"):
        return BOLD_ITEM_RE.findall(blocks.get(dotted, ""))
    if dotted == "qa.owner":
        return BOLD_ITEM_RE.findall(blocks.get("qa", ""))
    if dotted.startswith("stack."):
        field = dotted.split(".", 1)[1]
        block = blocks.get("stack", "")
        idx = block.find(LOCAL_RUN_MARKER)
        if idx == -1:
            return BOLD_ITEM_RE.findall(block)
        shared, local_run_part = block[:idx], block[idx:]
        return BOLD_ITEM_RE.findall(local_run_part if field == "local_run" else shared)
    return None


@pytest.mark.parametrize("dotted,value", adapter_cases())
def test_given_enum_value_then_adapter_file_exists_and_is_complete(dotted, value):
    path = concern_dir(dotted) / f"{value}.md"
    assert path.exists(), f"missing adapter file for {dotted}={value}: {path}"
    text = path.read_text(encoding="utf-8")

    blocks = parse_concern_blocks()
    headings = required_headings(dotted, blocks)
    if headings:
        found = re.findall(r"(?m)^##\s+(.+)$", text)
        missing = [h for h in headings if h not in found]
        assert missing == [], f"{path} is missing required headings: {missing}"
    else:
        assert text.strip(), f"{path} is empty"
