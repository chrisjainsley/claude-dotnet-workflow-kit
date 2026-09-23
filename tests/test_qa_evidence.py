import re
import shutil

import pytest

from conftest import BUILD_REVIEW_PY, CHECK_REVIEW_PY, FIXTURES_DIR, run_py

EVIDENCE_FIXTURE = FIXTURES_DIR / "review-evidence.md"
WHEN_STEP = "When an admin grants the signup campaign to their alias account"


@pytest.fixture()
def evidence_review(tmp_path):
    path = tmp_path / "review.md"
    shutil.copy(EVIDENCE_FIXTURE, path)
    shutil.copytree(FIXTURES_DIR / "evidence", tmp_path / "evidence")
    return path


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def build(path, tmp_path):
    out_path = tmp_path / "review.html"
    code, out, err = run_py(BUILD_REVIEW_PY, path, "--out", out_path, "--range", "deadbeef^..deadbeef")
    assert code == 0, out + err
    return out_path.read_text(encoding="utf-8"), out + err


def step_block(page, text):
    """The rendered element for the step whose text starts with `text`."""
    start = page.index(text)
    open_at = max(page.rfind('<details class="step">', 0, start), page.rfind('<div class="step">', 0, start))
    if page.startswith("<details", open_at):
        return page[open_at:page.index("</details>", open_at)]
    return page[open_at:page.index("</div>", open_at)]


def test_given_evidence_fixture_then_check_passes(evidence_review):
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 0, out + err
    assert "evidence images 1" in out


def test_given_captioned_evidence_then_step_collapses_with_it(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    when = step_block(page, "an admin grants the signup campaign")
    assert when.startswith('<details class="step">')
    assert "1 item" in when and "language-http" in when
    then = step_block(page, "the alias account&#x27;s balance is 0")
    assert "2 items" in then and "language-sql" in then and "<img" in then


def test_given_step_without_evidence_then_plain(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    given = step_block(page, "a member who already holds the signup grant")
    assert given.startswith('<div class="step">')


def test_given_evidence_image_then_inlined_inside_step(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    then = step_block(page, "the alias account&#x27;s balance is 0")
    assert 'src="data:image/png;base64,' in then


def test_given_evidence_and_classification_lines_then_separate_paragraphs(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    assert re.search(r'<p class="qa-evidence">.*?option rendered ticked on first load</p>', page)
    assert '<p class="qa-classification"><span class="qa-label">Classification</span> regression</p>' in page


def test_given_unmatched_caption_then_exit1(evidence_review, tmp_path):
    edit(evidence_review, f"```http {WHEN_STEP}", "```http When the member pays")
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "'When the member pays' under 'Repeat payer is refused' names no step" in out
    _, log = build(evidence_review, tmp_path)
    assert "names no step" in log


def test_given_uncaptioned_evidence_then_exit1(evidence_review):
    edit(evidence_review, f"```http {WHEN_STEP}", "```http")
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "an uncaptioned http block" in out


def test_given_caption_differs_in_case_and_spacing_then_matches(evidence_review):
    edit(evidence_review, f"```http {WHEN_STEP}", "```http when an ADMIN grants  the signup campaign to their alias account.")
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 0, out + err


@pytest.mark.parametrize("line, what", [
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9", "Authorization header"),
    ("Cookie: session=abc123", "cookie"),
    ('{"apiKey": "sk-live-123"}', "API key"),
    ("Server=db;User Id=sa;Password=hunter2;", "password"),
])
def test_given_credential_in_evidence_then_exit1(evidence_review, line, what):
    edit(evidence_review, "Authorization: Bearer <redacted>", line)
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert f"unredacted {what} in evidence under 'Repeat payer is refused'" in out


def test_given_redacted_credentials_then_passes(evidence_review):
    edit(evidence_review, "Authorization: Bearer <redacted>",
         "Authorization: Bearer <redacted>\nCookie: <redacted>\nx-api-key: <redacted>")
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 0, out + err


def test_given_eleven_images_then_exit1(evidence_review):
    image = "![Then the alias account's balance is 0](evidence/wallet.png)"
    edit(evidence_review, image, "\n".join([image] * 11))
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "QA report: 11 evidence images, cap 10" in out


def test_given_exemplar_without_evidence_then_unchanged(review_fixture_path, tmp_path):
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)
    assert code == 0, out + err
    page, _ = build(review_fixture_path, tmp_path)
    assert '<div class="steps">' not in page
    assert "No QA run." in page
