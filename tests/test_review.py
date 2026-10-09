import json
import re
from pathlib import Path

import pytest

from conftest import (
    BUILD_REVIEW_PY,
    CHECK_REVIEW_PY,
    FIXTURES_DIR,
    PAGE_TEMPLATE,
    RENDER_PY,
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
    module = import_module_from_path("render_secret_test", RENDER_PY)
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
    page = module.build(meta, sections, PAGE_TEMPLATE.read_text(encoding="utf-8"), open_count)

    assert "appsettings.Production.json" in page
    assert "not embedded" in page.lower()
    secret_block = page[page.index('id="file-appsettings-production-json"'):]
    secret_block = secret_block[: secret_block.index("</details>")]
    assert "not embedded" in secret_block.lower()
    assert "<pre><code" not in secret_block


FLOWMAP_RE = r"```flowmap\r?\n.*?\r?\n```\r?\n"


def test_given_missing_flowmap_then_exit1(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    text = re.sub(FLOWMAP_RE + r"\r?\n", "", text, count=1, flags=re.S)
    assert "```flowmap" not in text
    review_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 1
    assert "needs exactly one ```flowmap" in out


def test_given_legacy_mermaid_instead_of_flowmap_then_passes(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    mermaid = "```mermaid\nflowchart LR\n  A[relying party]:::changed --> B[session]:::ctx\n```\n"
    text = re.sub(FLOWMAP_RE, lambda _: mermaid, text, count=1, flags=re.S)
    # With no layer map there are no boxes, so the walkthrough points at the section.
    text = text.replace("`@web-rp`", "`Changes`").replace("`@mobile-rp`", "`Changes`")
    review_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 0, out + err


@pytest.mark.parametrize("old, new, message", [
    ("lanes: Infrastructure", "lanes: Policies", "lane 'Policies' is not a slice"),
    ("web-rp -> web-tp", "web-rp -> nowhere", "unknown node 'nowhere'"),
    ("  covers: web-rp", "  covers: web-gone", "covers unknown node 'web-gone'"),
    ("  status: context\n\nnode mobile-sso", "  status: gone\n\nnode mobile-sso", "status must be one of"),
    ("rows: Web sign-in, Mobile sign-in", "rows: Web sign-in", "row 'Mobile sign-in' is not in the rows line"),
])
def test_given_broken_flowmap_then_exit1(review_fixture_path, old, new, message):
    text = review_fixture_path.read_text(encoding="utf-8")
    assert old in text
    review_fixture_path.write_text(text.replace(old, new, 1), encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 1
    assert message in out


def test_given_example_for_unknown_node_then_exit1(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    example = "```xml @web-ghost Policy fragment\n<SingleSignOn />\n```\n\n### User Service"
    review_fixture_path.write_text(text.replace("### User Service", example, 1), encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 1
    assert "example '@web-ghost' names no node" in out


def test_given_example_for_known_node_then_passes(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    example = (
        "```xml @web-rp Relying party fragment\n<SingleSignOn Scope=\"Tenant\" KeepAliveInDays=\"90\" />\n```\n\n"
        "```record @web-sso Session cookie\nName | x-ms-cpim-sso | tenant scoped\nLifetime | 90 days | was 1 day\n```\n\n"
        "### User Service"
    )
    review_fixture_path.write_text(text.replace("### User Service", example, 1), encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 0, out + err


def test_given_example_after_service_heading_then_exit1_and_spacing_does_not_matter(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    before = "```JSON  @web-rp Session settings\n{\"keepAliveInDays\": 90}\n```\n\n### User Service"
    after = "| Tests | none |"
    late = "```xml @web-tp Profile fragment\n<Item />\n```\n\n| Tests | none |"
    text = text.replace("### User Service", before, 1).replace(after, late, 1)
    review_fixture_path.write_text(text, encoding="utf-8")

    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path)

    assert code == 1
    assert "example '@web-tp Profile fragment' belongs before the first ###" in out
    assert "@web-rp" not in out


MAP_REVIEW = """---
title: Cancel an order
base: dev
---

## Changes

```flowmap
lanes: API, Domain
rows: Orders

node endpoint: CancelOrderMutation
  lane: API
  file: src/Api/CancelOrderMutation.cs
  kind: api

node setter: Order.SetStatus
  lane: Domain
  file: src/Domain/OrderSetter.cs

node order: Order.Cancel
  lane: Domain
  file: src/Domain/Order.cs

test order-tests: OrderTests
  covers: order
  file: tests/Domain/OrderTests.cs

endpoint -> order
before: order -> setter: sets status
```

```graphql @endpoint Query
mutation { cancelOrder(input: { orderId: "1" }) { status } }
```

```record @order Example row · dbo.Orders
Status | Cancelled | was Placed
CancelledAt | 2026-10-08T09:14:22Z
```

### Orders

| Slice | File | Change |
|---|---|---|
| API | `src/Api/CancelOrderMutation.cs` | new mutation |
"""


def render_map(statuses):
    module = import_module_from_path("render_flowmap_test", RENDER_PY)
    module.META = {"base": "dev"}
    module.DIFF_RANGE = "deadbeef^..deadbeef"
    module.FILE_STATS = {path: ("3", "1") for path in statuses}
    module.FILE_STATUS = dict(statuses)
    module.USED_FILES = []
    module.WARNINGS = []
    meta, sections, _ = module.parse(MAP_REVIEW)
    page = module.build(meta, sections, PAGE_TEMPLATE.read_text(encoding="utf-8"))
    return module, page


def template_of(page, node):
    block = page[page.index(f'<template id="fm1-{node}">'):]
    return block[:block.index("</template>")]


ALL_CHANGED = {
    "src/Api/CancelOrderMutation.cs": "A",
    "src/Domain/OrderSetter.cs": "D",
    "src/Domain/Order.cs": "M",
    "tests/Domain/OrderTests.cs": "M",
}


def test_given_flowmap_then_nodes_take_git_status_and_views():
    module, page = render_map(ALL_CHANGED)

    assert '<figure class="flowmap" id="fm1" data-view="after"' in page
    assert 'class="fm-node s-new" data-node="endpoint" data-views="after"' in page
    assert 'class="fm-node s-deleted" data-node="setter" data-views="before"' in page
    assert 'class="fm-node s-modified" data-node="order" data-views="before after"' in page
    assert 'data-node="order-tests"' in page
    assert "Before · dev" in page
    assert '"views": ["before"]' in page
    # Every node's file is embedded once under File diffs; the dialog copies it from there.
    for path in ("src/Domain/OrderSetter.cs", "tests/Domain/OrderTests.cs"):
        assert path in module.USED_FILES
    assert page.count('id="file-src-api-cancelordermutation-cs"') == 1
    assert 'data-file="file-src-domain-order-cs"' in template_of(page, "order")


def test_given_flowmap_examples_then_they_render_in_the_node_dialog_only():
    _, page = render_map(ALL_CHANGED)

    endpoint = template_of(page, "endpoint")
    assert "cancelOrder" in endpoint
    assert 'class="language-graphql"' in endpoint
    order = template_of(page, "order")
    assert '<table class="fm-record">' in order
    assert "was Placed" in order
    outside = re.sub(r"<template.*?</template>", "", page, flags=re.S)
    assert "cancelOrder(input" not in outside


def test_given_flowmap_node_file_outside_diff_then_context_and_no_diff():
    _, page = render_map({"src/Api/CancelOrderMutation.cs": "A"})

    assert 'class="fm-node s-context" data-node="order"' in page
    assert "Not changed on this branch" in template_of(page, "order")


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


WALKTHROUGH_HEAD = "\n## Walkthrough\n"
WALK_ON = ("--profile", FIXTURES_DIR / "profile-walkthrough.json")


def scene_data(page):
    data = re.search(r'<script type="application/json" class="wt-data">(.*?)</script>', page, re.S).group(1)
    return json.loads(data)


def test_given_walkthrough_targets_then_each_must_resolve(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    assert WALKTHROUGH_HEAD in text
    broken = (text.replace("`@web-rp`", "`@no-such-node`", 1)
                  .replace("`Findings > useLogoutRedirect`", "`Findings > nowhere-on-the-page`", 1)
                  .replace("`QA report`", "`Testing`", 1))
    review_fixture_path.write_text(broken, encoding="utf-8")
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path, *WALK_ON)
    assert code == 1
    assert "@no-such-node, which is not a flowmap node" in out
    assert "'nowhere-on-the-page' in Findings" in out
    assert "'Testing', which is not a section of this document" in out


def test_given_walkthrough_written_for_the_eye_then_check_fails(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    text = text.replace("so ten of eleven acceptance criteria are delivered.",
                        "so 10/11 criteria are delivered in `B2C_1A_SIGNUP_SIGNIN.xml`.", 1)
    text = text.replace("8. `Decision`", "8. `Rollout` One more.\n9. `Decision`", 1)
    review_fixture_path.write_text(text, encoding="utf-8")
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path, *WALK_ON)
    assert code == 1
    assert "scene 1 has a slash count" in out
    assert "scene 1 has markdown or markup" in out
    assert "9 scenes, cap 8" in out


def test_given_walkthrough_off_then_section_is_not_checked_and_no_player(tmp_path, review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    review_fixture_path.write_text(text.replace("`@web-rp`", "`@no-such-node`", 1), encoding="utf-8")
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path, "--profile", FIXTURES_DIR / "profile-checks.json")
    assert code == 0, out + err
    assert "optional.walkthrough is false" in out
    out_path = tmp_path / "review.html"
    code, out, err = run_py(BUILD_REVIEW_PY, review_fixture_path, "--out", out_path, "--range", "deadbeef^..deadbeef",
                            "--profile", FIXTURES_DIR / "profile-checks.json")
    assert code == 0, out + err
    assert "ignored because optional.walkthrough is false" in err
    page = out_path.read_text(encoding="utf-8")
    assert 'id="wt"' not in page and 'id="walkthrough"' not in page and "{{" not in page


def test_given_walkthrough_before_decision_then_section_order_fails(review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    walk = text[text.index(WALKTHROUGH_HEAD):]
    text = text.replace(walk, "\n").replace("\n## Decision\n", walk + "\n## Decision\n", 1)
    review_fixture_path.write_text(text, encoding="utf-8")
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path, *WALK_ON)
    assert code == 1
    assert "then an optional Walkthrough" in out


def test_given_walkthrough_on_then_page_carries_the_player_not_a_section(tmp_path, review_fixture_path):
    out_path = tmp_path / "review.html"
    code, out, err = run_py(BUILD_REVIEW_PY, review_fixture_path, "--out", out_path, "--range", "deadbeef^..deadbeef", *WALK_ON)
    assert code == 0, out + err
    assert "16 sentence(s) have no recorded clip" in err
    page = out_path.read_text(encoding="utf-8")
    assert '<section class="wt" id="wt"' in page
    assert 'id="walkthrough"' not in page and 'data-target="walkthrough"' not in page
    assert "<select" not in page[page.index('id="wt"'):page.index("</section>", page.index('id="wt"'))]
    scenes = scene_data(page)
    assert len(scenes) == 8
    assert scenes[0]["section"] == "verdict" and "find" not in scenes[0]
    assert scenes[1]["node"] == "web-rp"
    assert (scenes[3]["section"], scenes[3]["find"]) == ("findings", "B2C_1A_MOBILE_SIGNIN")
    assert [l["text"] for l in scenes[0]["lines"]] == [
        "This change merged on the tenth of September.",
        "Web members can now stay signed in for ninety days.",
        "Mobile members cannot, so ten of eleven acceptance criteria are delivered.",
    ]
    assert "{{" not in page


def test_given_page_template_then_no_browser_voice():
    template = PAGE_TEMPLATE.read_text(encoding="utf-8")
    assert "speechSynthesis" not in template and "wt-voice" not in template


def test_given_no_walkthrough_then_check_passes_and_no_player(tmp_path, review_fixture_path):
    text = review_fixture_path.read_text(encoding="utf-8")
    review_fixture_path.write_text(text[: text.index(WALKTHROUGH_HEAD) + 1], encoding="utf-8")
    code, out, err = run_py(CHECK_REVIEW_PY, review_fixture_path, *WALK_ON)
    assert code == 0, out + err
    out_path = tmp_path / "review.html"
    code, out, err = run_py(BUILD_REVIEW_PY, review_fixture_path, "--out", out_path, "--range", "deadbeef^..deadbeef", *WALK_ON)
    assert code == 0, out + err
    page = out_path.read_text(encoding="utf-8")
    assert 'id="wt"' not in page
    assert "{{" not in page


def fake_synth(calls):
    def synth(text):
        calls.append(text)
        return [0.0, 0.1, -0.1] * 100, 24000
    return synth


def load_narrate(name):
    return import_module_from_path(name, RENDER_PY.parent / "narrate.py")


def test_given_walkthrough_then_narrate_records_each_sentence_once(review_fixture_path):
    narrate = load_narrate("narrate_test")
    calls = []
    recorded, kept, removed = narrate.narrate(review_fixture_path, fake_synth(calls), mp3=False)
    assert recorded == len(calls) == len(set(calls)) == 16
    assert (kept, removed) == (0, 0)
    clip_dir = review_fixture_path.parent / "walkthrough" / "review"
    manifest = json.loads((clip_dir / "narration.json").read_text(encoding="utf-8"))
    assert manifest["voice"] == "af_heart"
    assert all((review_fixture_path.parent / c["file"]).is_file() for c in manifest["clips"])

    # A changed line records only itself and drops its old clip.
    text = review_fixture_path.read_text(encoding="utf-8")
    review_fixture_path.write_text(text.replace("Nothing has run against a live tenant yet.", "No live tenant run exists yet.", 1), encoding="utf-8")
    calls.clear()
    recorded, kept, removed = narrate.narrate(review_fixture_path, fake_synth(calls), mp3=False)
    assert calls == ["No live tenant run exists yet."]
    assert (recorded, kept, removed) == (1, 15, 1)


def test_given_recorded_clips_then_page_plays_and_publishes_them(review_fixture_path):
    narrate = load_narrate("narrate_test2")
    narrate.narrate(review_fixture_path, fake_synth([]), mp3=False)
    (review_fixture_path.parent / "walkthrough" / "review" / (narrate.clip_name("The whole change is policy XML.") + ".wav")).unlink()
    out_path = review_fixture_path.parent / "review.html"
    code, out, err = run_py(BUILD_REVIEW_PY, review_fixture_path, "--out", out_path, "--range", "deadbeef^..deadbeef", *WALK_ON)
    assert code == 0, out + err
    assert "1 sentence(s) have no recorded clip and play as captions only" in err
    lines = [l for sc in scene_data(out_path.read_text(encoding="utf-8")) for l in sc["lines"]]
    assert sum(1 for l in lines if "audio" not in l) == 1
    files = json.loads((review_fixture_path.parent / "review.files.json").read_text(encoding="utf-8"))
    assert len(files) == len(lines) - 1
    assert all(f.startswith("walkthrough/review/") and f.endswith(".wav") for f in files)


def test_given_walkthrough_off_then_narrate_records_nothing(review_fixture_path):
    narrate = load_narrate("narrate_test3")
    assert narrate.main([str(review_fixture_path), "--profile", str(FIXTURES_DIR / "profile-checks.json")]) == 0
    assert not (review_fixture_path.parent / "walkthrough").exists()


def test_given_no_kokoro_then_narrate_exits_2(review_fixture_path, monkeypatch):
    narrate = load_narrate("narrate_test4")
    monkeypatch.setattr(narrate, "kokoro_engine", lambda *a: None)
    assert narrate.main([str(review_fixture_path), "--profile", str(FIXTURES_DIR / "profile-walkthrough.json")]) == 2
    assert not (review_fixture_path.parent / "walkthrough").exists()
