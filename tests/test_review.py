from pathlib import Path

import pytest

from conftest import (
    BUILD_REVIEW_PY,
    CHECK_REVIEW_PY,
    FIXTURES_DIR,
    REVIEW_TEMPLATE,
    import_module_from_path,
    run_py,
)

NO_QA_RUN_LINE = "**No QA run.** This review holds no evidence from a running system.\n\n"


def test_given_fixture_matches_exemplar(review_fixture_text):
    checked_in = (FIXTURES_DIR / "review.md").read_text(encoding="utf-8")
    assert checked_in == review_fixture_text


def test_given_exemplar_fixture_then_check_passes(review_fixture_path):
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)
    assert code == 0, out + err
    assert "OK" in out


def test_given_no_qa_run_marker_then_passes(review_fixture_path):
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)
    assert code == 0, out + err

    text = review_fixture_path.read_text(encoding="utf-8")
    assert NO_QA_RUN_LINE in text
    stripped = text.replace(NO_QA_RUN_LINE, "", 1)
    review_fixture_path.write_text(stripped, encoding="utf-8")

    code2, out2, err2 = run_py(CHECK_REVIEW_PY, review_fixture_path)
    assert code2 == 1
    assert "no scenario headings" in out2


def test_given_merged_state_then_build_renders_follow_up_form(tmp_path, review_fixture_path):
    out_path = tmp_path / "review.html"
    code, out, err = run_py(
        BUILD_REVIEW_PY,
        review_fixture_path,
        "--template", REVIEW_TEMPLATE,
        "--out", out_path,
        "--range", "deadbeef^..deadbeef",
    )
    assert code == 0, out + err
    html = out_path.read_text(encoding="utf-8")
    assert "Needs follow-up" in html
    assert "Post the QA report to the work item and close this review" in html
    assert 'name="verdict" value="approve"' in html
    assert 'name="verdict" value="changes"' in html


def test_given_secret_file_in_changes_table_then_not_embedded(review_fixture_text):
    module = import_module_from_path("build_review_secret_test", BUILD_REVIEW_PY)
    text = review_fixture_text.replace(
        "| Tests | none | B2C policy XML has no test host in this repo |",
        "| Tests | none | B2C policy XML has no test host in this repo |\n"
        "| Infrastructure | `appsettings.Production.json` | rotate database connection string |",
        1,
    )

    module.META = {}
    module.FILE_STATS = {"appsettings.Production.json": ("1", "1")}
    module.USED_FILES = []
    module.WARNINGS = []

    meta, sections, open_count = module.parse(text)
    page = module.build(meta, sections, REVIEW_TEMPLATE.read_text(encoding="utf-8"), open_count)

    assert "appsettings.Production.json" in page
    assert "not embedded" in page.lower()
    secret_block = page[page.index('id="file-appsettings-production-json"'):]
    secret_block = secret_block[: secret_block.index("</details>")]
    assert "not embedded" in secret_block.lower()
    assert "<pre><code" not in secret_block


def test_given_missing_mermaid_then_exit1(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    import re

    text = re.sub(r"```mermaid\r?\n.*?\r?\n```\r?\n\r?\n", "", text, count=1, flags=re.S)
    assert "```mermaid" not in text
    review_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 1
    assert "needs exactly one" in out


def test_given_nine_hunks_then_exit1(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    extra = ""
    for i in range(3, 10):
        extra += f"\n\n#### Extra hunk {i}\n\n```diff\n+extra change line {i}\n```\n"
    assert "\n## Contracts and coordination" in text
    text = text.replace("\n## Contracts and coordination", extra + "\n## Contracts and coordination", 1)
    review_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 1
    assert "9 diff hunks, cap 8" in out
