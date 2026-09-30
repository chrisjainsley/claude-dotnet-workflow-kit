import json
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
    assert "evidence images 1, evidence videos 1" in out


def test_given_captioned_evidence_then_step_collapses_with_it(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    when = step_block(page, "an admin grants the signup campaign")
    assert when.startswith('<details class="step">')
    assert "1 item" in when and "language-http" in when
    then = step_block(page, "the alias account&#x27;s balance is 0")
    assert "1 item" in then and "language-sql" in then and "<img" not in then
    assert "shot below" not in then


def test_given_step_without_evidence_then_plain(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    given = step_block(page, "a member who already holds the signup grant")
    assert given.startswith('<div class="step">')


def media_grid(page):
    start = page.index('<div class="figures qa-media">')
    return page[start:page.index("</div>", start)]


def test_given_evidence_image_then_linked_in_visible_grid_after_steps(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    grid = media_grid(page)
    assert page.index('<div class="steps">') < page.index(grid)
    assert '<figure class="shot"><img src="evidence/wallet.png"' in grid
    assert '<span class="kw">Then</span> the alias account' in grid
    assert "data:image/png;base64," not in page


def test_given_video_captioned_with_scenario_title_then_plays_in_grid_without_warning(evidence_review, tmp_path):
    page, log = build(evidence_review, tmp_path)
    grid = media_grid(page)
    assert '<video controls preload="metadata" playsinline src="evidence/run.webm"' in grid
    assert "names no step" not in log
    files = json.loads((tmp_path / "review.files.json").read_text(encoding="utf-8"))
    assert files == ["evidence/run.webm", "evidence/wallet.png"]
    assert "evidence files: 2 (review.files.json)" in log


def test_given_two_images_on_a_scenario_then_one_grid(evidence_review, tmp_path):
    image = "![Then the alias account's balance is 0](evidence/wallet.png)"
    edit(evidence_review, image, image + "\n![Given a member who already holds the signup grant](evidence/wallet.png)")
    page, _ = build(evidence_review, tmp_path)
    assert page.count('<div class="figures qa-media">') == 1
    assert media_grid(page).count('<figure class="shot">') == 2
    assert step_block(page, "a member who already holds the signup grant").startswith('<div class="step">')


def test_given_http_fence_with_status_line_then_request_and_response_panes(evidence_review, tmp_path):
    page, _ = build(evidence_review, tmp_path)
    when = step_block(page, "an admin grants the signup campaign")
    assert '<div class="evidence-item http-pair">' in when
    assert '<code class="http-line">POST /graphql</code>' in when
    assert '<span class="pill pill-pass">200</span>' in when
    assert '&quot;message&quot;: &quot;payer already had the grant&quot;' not in when
    assert '"message": "payer already had the grant"' in when
    assert '{\n  "errors": [' in when
    request = when[when.index("Request"):when.index("Response")]
    assert "Content-Type: application/json\n\n{\n  &quot;query&quot;" in request or 'Content-Type: application/json\n\n{\n  "query"' in request
    assert '"userId": "member-2"' in request


def test_given_http_fence_with_error_status_then_fail_pill(evidence_review, tmp_path):
    edit(evidence_review, "HTTP/1.1 200 OK", "HTTP/2 409 Conflict")
    page, _ = build(evidence_review, tmp_path)
    assert '<span class="pill pill-fail">409</span>' in step_block(page, "an admin grants the signup campaign")


def test_given_http_fence_without_status_line_then_plain_block(evidence_review, tmp_path):
    edit(evidence_review, "HTTP/1.1 200 OK\n", "")
    page, _ = build(evidence_review, tmp_path)
    when = step_block(page, "an admin grants the signup campaign")
    assert "http-pair" not in when and "language-http" in when


def test_given_missing_evidence_file_then_exit1(evidence_review, tmp_path):
    (tmp_path / "evidence" / "wallet.png").unlink()
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "evidence file evidence/wallet.png under 'Repeat payer is refused' does not exist" in out
    page, _ = build(evidence_review, tmp_path)
    assert "Missing image: evidence/wallet.png" in page


def test_given_four_videos_then_exit1(evidence_review):
    video = "![Repeat payer is refused](evidence/run.webm)"
    edit(evidence_review, video, "\n".join([video] * 4))
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "QA report: 4 evidence videos, cap 3" in out


def test_given_oversized_evidence_file_then_exit1(evidence_review, tmp_path):
    with open(tmp_path / "evidence" / "run.webm", "ab") as f:
        f.truncate(16 * 1024 * 1024)
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "evidence/run.webm is 16.0 MB, cap 15 MB per file" in out


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
    ("X-Api-Token: abc123", "token"),
    ("X-Hub-Signature-256: sha256=abc", "X-Hub-Signature-256 header"),
    ("Ocp-Apim-Subscription-Key: abc123", "Ocp-Apim-Subscription-Key header"),
    ('curl -H "X-Session-Key: abc" https://api.test', "X-Session-Key header"),
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


@pytest.mark.parametrize("line, what", [
    ('curl -H "Authorization: Bearer abc.def" https://api.test/orders', "Authorization header"),
    ('{"headers": {"Authorization": "Bearer abc"}}', "Authorization header"),
    ('{"access_token": "eyJhbGciOi"}', "token"),
    ('{"client_secret": "zzz"}', "secret"),
    ('{"newPassword": "hunter2"}', "password"),
    ("Cookie: session=abc123; csrf=<redacted>", "cookie"),
])
def test_given_credential_outside_a_plain_header_then_exit1(evidence_review, line, what):
    edit(evidence_review, "Authorization: Bearer <redacted>", line)
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert f"unredacted {what} in evidence" in out


@pytest.mark.parametrize("line", [
    '{"password": null, "passwordReset": true, "token_type": "Bearer"}',
    "Set-Cookie: session=<redacted>; Path=/; HttpOnly",
])
def test_given_credential_words_without_secrets_then_passes(evidence_review, line):
    edit(evidence_review, "Authorization: Bearer <redacted>", line)
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 0, out + err


def test_given_heading_inside_evidence_fence_then_still_checked(evidence_review):
    edit(evidence_review, "Authorization: Bearer <redacted>\n", "Authorization: Bearer abc123\n#### Response\n")
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert "unredacted Authorization header in evidence under 'Repeat payer is refused'" in out


def test_given_star_step_then_evidence_attaches(evidence_review, tmp_path):
    edit(evidence_review, f"{WHEN_STEP}\nThen", f"* {WHEN_STEP[5:]}\nThen")
    edit(evidence_review, f"```http {WHEN_STEP}", f"```http * {WHEN_STEP[5:]}")
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 0, out + err
    page, _ = build(evidence_review, tmp_path)
    assert step_block(page, "an admin grants the signup campaign").startswith('<details class="step">')


def test_given_quote_in_fence_language_then_escaped(evidence_review, tmp_path):
    edit(evidence_review, f"```http {WHEN_STEP}", f'```j"onclick="x {WHEN_STEP}')
    page, _ = build(evidence_review, tmp_path)
    assert 'class="language-j&quot;onclick=&quot;x"' in page
    assert 'onclick="x"' not in page


@pytest.mark.parametrize("line, what", [
    ("Authorization: Bearer <redacted>suffix", "Authorization header"),
    ('{"Authorization": "Bearer <redacted>x"}', "Authorization header"),
    ("apiKey: <redacted>suffix", "API key"),
])
def test_given_text_after_redacted_marker_then_exit1(evidence_review, line, what):
    edit(evidence_review, "Authorization: Bearer <redacted>", line)
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 1
    assert f"unredacted {what} in evidence" in out


def test_given_redacted_json_authorization_then_passes(evidence_review):
    edit(evidence_review, "Authorization: Bearer <redacted>",
         '{"Authorization": "Bearer <redacted>", "token": "<redacted>"}\ncurl -H "Authorization: Bearer <redacted>"')
    code, out, err = run_py(CHECK_REVIEW_PY, evidence_review)
    assert code == 0, out + err
