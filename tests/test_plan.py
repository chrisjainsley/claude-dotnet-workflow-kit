import json
import re
from pathlib import Path

import pytest

from conftest import (
    BUILD_PLAN_PY,
    CHECK_PLAN_PY,
    FIXTURES_DIR,
    RENDER_PY,
    import_module_from_path,
    run_py,
)


def test_given_fixture_matches_exemplar(plan_fixture_text):
    checked_in = (FIXTURES_DIR / "plan.md").read_text(encoding="utf-8")
    assert checked_in == plan_fixture_text


def test_given_exemplar_fixture_then_check_passes(plan_fixture_path):
    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)
    assert code == 0, out + err
    assert "OK" in out


def test_given_over_budget_section_then_exit1(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    filler = " word" * 200
    text = text.replace(
        "Today the credit is per account, so a second account is another $10.",
        "Today the credit is per account, so a second account is another $10." + filler,
        1,
    )
    plan_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)

    assert code == 1
    assert "Requirement" in out
    assert "OVER" in out


def test_given_missing_section_then_exit1(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    text = re.sub(r"\n## Domain\n.*?(?=\n## Application\n)", "\n", text, flags=re.S)
    plan_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)

    assert code == 1
    assert "sections must be exactly" in out


def test_given_question_with_two_recommended_then_exit1(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    text = text.replace(
        "   - [ ] **Include now.** Adds a B2C policy PR, a connector model field and a second payer key to this stack.",
        "   - [x] **Include now.** Adds a B2C policy PR, a connector model field and a second payer key to this stack.",
        1,
    )
    plan_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path)

    assert code == 1
    assert "exactly one [x]" in out


def test_given_fixture_then_build_writes_html_with_question_form(tmp_path, plan_fixture_text):
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(plan_fixture_text, encoding="utf-8")
    out_path = tmp_path / "plan.html"

    code, out, err = run_py(BUILD_PLAN_PY, plan_path, "--out", out_path)

    assert code == 0, out + err
    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert '<form class="qform"' in html
    assert "Include the durable sign-in identity in this story?" in html
    assert "Backfill payer claims for grants PR 3081 already issued on sandbox and dev?" in html
    assert "Anything else to preserve or avoid?" in html
    assert 'type="radio"' in html


def test_given_vertical_profile_then_check_expects_slice_sections(tmp_path, plan_fixture_path):
    profile_path = tmp_path / "vertical-profile.json"
    profile_path.write_text(json.dumps({"architecture": "vertical"}), encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path, "--profile", profile_path)

    assert code == 1
    assert "Slice" in out


VERTICAL_FIXTURE_PATH = FIXTURES_DIR / "plan-vertical.md"
VERTICAL_PROFILE_PATH = FIXTURES_DIR / "profile-vertical.json"
VERTICAL_SECTIONS = [
    "Context", "Requirement", "Specs", "Slice", "Persistence", "Integration",
    "Endpoint", "Tests", "Decisions", "Risks and rollout", "Open questions",
]


def test_given_vertical_fixture_then_check_passes():
    code, out, err = run_py(CHECK_PLAN_PY, VERTICAL_FIXTURE_PATH, "--profile", VERTICAL_PROFILE_PATH)

    assert code == 0, out + err
    assert "OK" in out


def test_given_vertical_fixture_then_build_renders_all_sections(tmp_path):
    out_path = tmp_path / "plan-vertical.html"

    code, out, err = run_py(BUILD_PLAN_PY, VERTICAL_FIXTURE_PATH, "--out", out_path)

    assert code == 0, out + err
    html = out_path.read_text(encoding="utf-8")
    for name in VERTICAL_SECTIONS:
        assert f"<h2>{name}</h2>" in html, name


def test_given_vertical_fixture_with_clean_profile_then_check_fails():
    code, out, err = run_py(CHECK_PLAN_PY, VERTICAL_FIXTURE_PATH)

    assert code == 1
    assert "sections must be exactly" in out


DESIGNS_FIXTURE_PATH = FIXTURES_DIR / "plan-designs.md"
BLAZOR_PROFILE_PATH = FIXTURES_DIR / "profile-blazor.json"


def test_given_designs_after_specs_and_frontend_blazor_then_check_passes():
    code, out, err = run_py(CHECK_PLAN_PY, DESIGNS_FIXTURE_PATH, "--profile", BLAZOR_PROFILE_PATH)

    assert code == 0, out + err
    assert "Designs" in out


def test_given_designs_with_frontend_none_then_exit1(tmp_path):
    profile_path = tmp_path / "none-profile.json"
    profile_path.write_text(json.dumps({"stack": {"frontend": "none"}}), encoding="utf-8")

    code, out, err = run_py(CHECK_PLAN_PY, DESIGNS_FIXTURE_PATH, "--profile", profile_path)

    assert code == 1
    assert "stack.frontend" in out


def test_given_designs_before_specs_then_exit1(tmp_path):
    text = DESIGNS_FIXTURE_PATH.read_text(encoding="utf-8")
    specs_at, designs_at = text.index("## Specs\n"), text.index("## Designs\n")
    domain_at = text.index("## Domain\n")
    swapped = text[:specs_at] + text[designs_at:domain_at] + text[specs_at:designs_at] + text[domain_at:]
    path = tmp_path / "plan.md"
    path.write_text(swapped, encoding="utf-8", newline="\n")

    code, out, err = run_py(CHECK_PLAN_PY, path, "--profile", BLAZOR_PROFILE_PATH)

    assert code == 1
    assert "sections must be exactly" in out


def test_given_dc_html_embed_then_build_emits_sandboxed_iframe_without_support_js(tmp_path):
    out_path = tmp_path / "plan.html"

    code, out, err = run_py(BUILD_PLAN_PY, DESIGNS_FIXTURE_PATH, "--out", out_path, "--profile", BLAZOR_PROFILE_PATH)

    assert code == 0, out + err
    html = out_path.read_text(encoding="utf-8")
    assert "<h2>Designs</h2>" in html
    figure = re.search(r'<figure class="design">.*?</figure>', html, re.S)
    assert figure, "no design figure rendered"
    assert 'sandbox=""' in figure.group(0)
    assert 'width="960" height="540"' in figure.group(0)
    assert "support.js" not in figure.group(0)
    assert "Earned points" in figure.group(0)
    # Designs is not an architecture layer, so it carries no onion ring index.
    assert re.search(r'<section class="plan-section" id="designs">', html)


def test_given_missing_dc_html_then_missing_figure(tmp_path):
    text = DESIGNS_FIXTURE_PATH.read_text(encoding="utf-8").replace("design/project/Main.dc.html", "design/project/Gone.dc.html")
    path = tmp_path / "plan.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    out_path = tmp_path / "plan.html"

    code, out, err = run_py(BUILD_PLAN_PY, path, "--out", out_path, "--profile", BLAZOR_PROFILE_PATH)

    assert code == 0, out + err
    assert "Missing artboard: design/project/Gone.dc.html" in out_path.read_text(encoding="utf-8")


WALK_ON = ("--profile", FIXTURES_DIR / "profile-walkthrough.json")


def plan_scenes(page):
    data = re.search(r'<script type="application/json" class="wt-data">(.*?)</script>', page, re.S).group(1)
    return json.loads(data)


def test_given_plan_walkthrough_on_then_check_validates_its_targets(plan_fixture_path):
    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path, *WALK_ON)
    assert code == 0, out + err
    assert "Walkthrough (spoken)" in out
    text = plan_fixture_path.read_text(encoding="utf-8")
    plan_fixture_path.write_text(text.replace("`Open questions > Backfill payer claims`", "`Open questions > Rewrite billing`", 1)
                                     .replace("`Requirement`", "`@payer-grain`", 1), encoding="utf-8")
    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path, *WALK_ON)
    assert code == 1
    assert "'Rewrite billing' in Open questions" in out
    assert "@payer-grain, which is not a flowmap node" in out


def test_given_plan_walkthrough_off_then_ignored(tmp_path, plan_fixture_path):
    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path, "--profile", FIXTURES_DIR / "profile-checks.json")
    assert code == 0, out + err
    assert "optional.walkthrough is false" in out
    out_path = tmp_path / "plan.html"
    code, out, err = run_py(BUILD_PLAN_PY, plan_fixture_path, "--out", out_path, "--profile", FIXTURES_DIR / "profile-checks.json")
    assert code == 0, out + err
    page = out_path.read_text(encoding="utf-8")
    assert 'id="wt"' not in page and 'id="walkthrough"' not in page


def test_given_plan_walkthrough_before_open_questions_then_order_fails(plan_fixture_path):
    text = plan_fixture_path.read_text(encoding="utf-8")
    walk = text[text.index("\n## Walkthrough\n"):]
    text = text.replace(walk, "\n").replace("\n## Open questions\n", walk + "\n## Open questions\n", 1)
    plan_fixture_path.write_text(text, encoding="utf-8")
    code, out, err = run_py(CHECK_PLAN_PY, plan_fixture_path, *WALK_ON)
    assert code == 1
    assert "then an optional Walkthrough" in out


def test_given_plan_walkthrough_on_then_player_points_at_the_questions(plan_fixture_path):
    narrate = import_module_from_path("narrate_plan_test", RENDER_PY.parent / "narrate.py")
    narrate.narrate(plan_fixture_path, lambda text: ([0.0] * 300, 24000), mp3=False)
    out_path = plan_fixture_path.parent / "plan.html"
    code, out, err = run_py(BUILD_PLAN_PY, plan_fixture_path, "--out", out_path, *WALK_ON)
    assert code == 0, out + err
    page = out_path.read_text(encoding="utf-8")
    assert '<section class="wt" id="wt"' in page
    assert 'data-target="walkthrough"' not in page
    scenes = plan_scenes(page)
    assert (scenes[5]["section"], scenes[5]["find"]) == ("open-questions", "durable sign-in identity")
    assert all("audio" in line for scene in scenes for line in scene["lines"])
    files = json.loads((plan_fixture_path.parent / "plan.files.json").read_text(encoding="utf-8"))
    assert files and all(f.startswith("walkthrough/plan/") for f in files)


def test_given_plan_and_review_in_one_folder_then_recordings_keep_apart(plan_fixture_path):
    narrate = import_module_from_path("narrate_shared_test", RENDER_PY.parent / "narrate.py")
    review = plan_fixture_path.parent / "review.md"
    review.write_text((FIXTURES_DIR / "review.md").read_text(encoding="utf-8"), encoding="utf-8")
    silent = lambda text: ([0.0] * 300, 24000)
    narrate.narrate(review, silent, mp3=False)
    narrate.narrate(plan_fixture_path, silent, mp3=False)
    root = plan_fixture_path.parent / "walkthrough"
    assert len(list((root / "review").glob("*.wav"))) == 16
    assert len(list((root / "plan").glob("*.wav"))) > 8
