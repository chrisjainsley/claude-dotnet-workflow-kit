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

NON_STACK_CONCERNS = ("architecture", "tracker", "scm", "qa.owner")


def concern_dir(dotted):
    if dotted == "qa.owner":
        return ADAPTERS_DIR / "qa"
    return ADAPTERS_DIR / dotted


def adapter_file_or_readme(dotted, value):
    """A non-stack adapter is either <concern>/<value>.md or <concern>/<value>/README.md."""
    base = concern_dir(dotted)
    plain = base / f"{value}.md"
    if plain.exists():
        return plain
    return base / value / "README.md"


def non_stack_cases():
    cases = []
    for dotted, values in profile_mod.ENUMS.items():
        if dotted not in NON_STACK_CONCERNS:
            continue
        for value in values:
            cases.append((dotted, value))
    return cases


def stack_fields():
    return [dotted.split(".", 1)[1] for dotted in profile_mod.ENUMS if dotted.startswith("stack.")]


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
    return None


@pytest.mark.parametrize("dotted,value", non_stack_cases())
def test_given_enum_value_then_adapter_file_exists_and_is_complete(dotted, value):
    path = adapter_file_or_readme(dotted, value)
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


@pytest.mark.parametrize("field", stack_fields())
def test_given_stack_field_then_one_file_holds_every_value_as_a_section(field):
    path = ADAPTERS_DIR / "stack" / f"{field}.md"
    assert path.exists(), f"missing stack adapter file: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path} is empty"

    found_headings = re.findall(r"(?m)^##\s+(.+)$", text)
    values = profile_mod.ENUMS[f"stack.{field}"]
    missing = [value for value in values if value not in found_headings]
    assert missing == [], f"{path} is missing '## <value>' sections: {missing}"


def test_given_azure_boards_tracker_then_it_is_a_folder_with_its_script():
    folder = ADAPTERS_DIR / "tracker" / "azure-boards"
    assert (folder / "README.md").exists(), "azure-boards adapter must be a folder with README.md"
    assert (folder / "fetch_context.py").exists(), "fetch_context.py must live under the azure-boards adapter"
    assert not (ADAPTERS_DIR / "tracker" / "azure-boards.md").exists(), (
        "azure-boards.md should have been replaced by the azure-boards/ folder"
    )
