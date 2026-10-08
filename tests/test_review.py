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
