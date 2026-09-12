"""The shared page template's inline script parses, and each kind gets only its own form."""
import re
import shutil

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
