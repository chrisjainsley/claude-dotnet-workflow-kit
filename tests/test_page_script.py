"""The shared page template's inline script parses, and each kind gets only its own form."""
import re
import shutil
from pathlib import Path

import pytest

from conftest import PAGE_TEMPLATE, RENDER_PY, run_py

INLINE_SCRIPT_RE = re.compile(r"<script>\s*(.*?)\s*</script>", re.S)


def inline_scripts():
    return INLINE_SCRIPT_RE.findall(PAGE_TEMPLATE.read_text(encoding="utf-8"))


def test_given_page_template_then_inline_script_parses(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; cannot syntax-check the inline page script")
    scripts = inline_scripts()
    assert scripts, "assets/page.html has no inline <script> block"
    for n, body in enumerate(scripts, start=1):
        path = tmp_path / f"page-script-{n}.js"
        path.write_text(body, encoding="utf-8")
        result = __import__("subprocess").run(
            [node, "--check", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_given_plan_source_then_only_the_answers_form_renders(tmp_path, plan_fixture_path):
    out_path = tmp_path / "plan.html"
    code, out, err = run_py(RENDER_PY, plan_fixture_path, "--out", out_path)
    assert code == 0, out + err

    page = out_path.read_text(encoding="utf-8")
    assert '<form class="qform" id="qform"' in page
    assert '<form class="dform"' not in page
    assert 'id="dform"' not in page
    assert 'class="layout kind-plan"' in page


def test_given_review_source_then_only_the_decision_form_renders(tmp_path, review_fixture_path):
    out_path = tmp_path / "review.html"
    code, out, err = run_py(
        RENDER_PY, review_fixture_path, "--out", out_path, "--range", "deadbeef^..deadbeef"
    )
    assert code == 0, out + err

    page = out_path.read_text(encoding="utf-8")
    assert '<form class="dform" id="dform"' in page
    assert '<form class="qform"' not in page
    assert 'id="qform"' not in page
    assert 'class="layout kind-review"' in page


def test_given_evidence_review_then_inline_script_parses(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; cannot syntax-check the inline page script")
    fixtures = Path(__file__).resolve().parent / "fixtures"
    source = tmp_path / "review.md"
    shutil.copy(fixtures / "review-evidence.md", source)
    shutil.copytree(fixtures / "evidence", tmp_path / "evidence")
    out_path = tmp_path / "review.html"
    code, out, err = run_py(RENDER_PY, source, "--out", out_path, "--range", "deadbeef^..deadbeef")
    assert code == 0, out + err
    scripts = INLINE_SCRIPT_RE.findall(out_path.read_text(encoding="utf-8"))
    assert scripts
    for n, body in enumerate(scripts, start=1):
        path = tmp_path / f"evidence-script-{n}.js"
        path.write_text(body, encoding="utf-8")
        result = __import__("subprocess").run(
            [node, "--check", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_given_page_template_then_both_forms_send_to_claude_with_a_chat_fallback():
    script = "\n".join(inline_scripts())
    assert "use('comments')" in script
    assert script.count("await sendToClaude(") == 2
    assert "canSendToClaude()" in script
    assert script.count('Tell Claude "decided"') == 2


def test_given_plan_and_review_skills_then_they_declare_comments_beside_db():
    root = Path(__file__).resolve().parents[1]
    for skill in ("plan", "review"):
        text = (root / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert '{"db": {}, "comments": {}}' in text, skill


def test_given_plan_source_then_the_form_ends_with_an_approve_or_revise_decision(tmp_path, plan_fixture_path):
    out_path = tmp_path / "plan.html"
    code, out, err = run_py(RENDER_PY, plan_fixture_path, "--out", out_path)
    assert code == 0, out + err
    page = out_path.read_text(encoding="utf-8")
    form = page[page.index('<form class="qform"'):]
    form = form[: form.index("</form>")]
    assert 'class="d plan-decision"' in form
    assert 'name="verdict" value="approve"' in form
    assert 'name="verdict" value="changes"' in form


def test_given_plan_with_no_open_questions_then_the_decision_form_still_renders(tmp_path, plan_fixture_path):
    text = Path(plan_fixture_path).read_text(encoding="utf-8")
    head, _, _ = text.partition("## Open questions")
    source = tmp_path / "plan.md"
    source.write_text(head + "## Open questions\nNone.\n", encoding="utf-8")
    out_path = tmp_path / "plan.html"
    code, out, err = run_py(RENDER_PY, source, "--out", out_path)
    assert code == 0, out + err
    page = out_path.read_text(encoding="utf-8")
    assert '<form class="qform" id="qform"' in page
    assert 'class="d plan-decision"' in page
    assert 'class="q"' not in page
