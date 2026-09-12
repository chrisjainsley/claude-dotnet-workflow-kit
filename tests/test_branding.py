import json

import pytest

from conftest import BUILD_PLAN_PY, BUILD_REVIEW_PY, run_py

BRAND_LINK = 'href="https://deliverylabs.co/workflow-kit"'


def write_profile(tmp_path, branding):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"schema": 1, "branding": branding}), encoding="utf-8")
    return path


def build(script, source, tmp_path, branding):
    out = tmp_path / "page.html"
    code, stdout, stderr = run_py(script, source, "--out", out, "--profile", write_profile(tmp_path, branding))
    assert code == 0, stdout + stderr
    return out.read_text(encoding="utf-8")


@pytest.mark.parametrize("branding", [True, False])
def test_given_plan_then_no_placeholder_leaks(plan_fixture_path, tmp_path, branding):
    page = build(BUILD_PLAN_PY, plan_fixture_path, tmp_path, branding)
    assert "{{" not in page


def test_given_branding_on_then_plan_carries_footer_and_indigo(plan_fixture_path, tmp_path):
    page = build(BUILD_PLAN_PY, plan_fixture_path, tmp_path, True)
    assert BRAND_LINK in page
    assert 'class="attribution"' in page
    assert "Delivery Labs" in page
    assert "#4F46E5" in page and "#818CF8" in page
    assert page.count(':root[data-theme="dark"]') == 2


def test_given_branding_off_then_plan_is_neutral(plan_fixture_path, tmp_path):
    page = build(BUILD_PLAN_PY, plan_fixture_path, tmp_path, False)
    assert "deliverylabs" not in page
    assert 'class="attribution"' not in page
    assert "#4F46E5" not in page


def test_given_branding_on_then_review_carries_footer(review_fixture_path, tmp_path):
    page = build(BUILD_REVIEW_PY, review_fixture_path, tmp_path, True)
    assert BRAND_LINK in page
    assert page.rindex('class="attribution"') > page.rindex("</main>")


def test_given_branding_off_then_review_has_no_footer(review_fixture_path, tmp_path):
    page = build(BUILD_REVIEW_PY, review_fixture_path, tmp_path, False)
    assert "deliverylabs" not in page


def test_given_non_boolean_branding_then_invalid():
    import kit_profile
    profile = json.loads(json.dumps(kit_profile.DEFAULTS))
    profile["branding"] = "yes"
    assert any("branding" in p for p in kit_profile.validate(profile))
