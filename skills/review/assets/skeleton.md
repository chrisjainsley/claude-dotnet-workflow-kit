---
title: <short name, two to five words, no ticket number>
ticket: <tracker id>
state: <open | merged>
pr: <PR URL>
branch: <per the profile's branch_pattern>
base: <profile base_branch, or the parent branch for a stacked layer>
commits: <n ahead of base, or "1 squash, <sha>" once merged>
files: <n changed, +a / -d>
ci: <green | red: job name | not run>
deployed: <where the change actually is: "<qa environment> run <n>", "not deployed", "local only">
size: <small | standard | large; tracks the number of rows the review needs, not the diff size>
date: <YYYY-MM-DD>
---

## Verdict
<!-- One or two sentences: ready for QA or not, and the single reason if not. Then the tiles table; every number must agree with the sections below. -->

| Metric | Value | Note |
|---|---|---|
| Acceptance | <pass>/<run> | <suite or feature, environment> |
| Manual QA | <pass>/<run> | <environment> |
| Findings open | <n> | <highest severity> |
| AC covered | <n>/<m> | <delivered in code: done plus changed rows; name what is dropped> |

## Plan versus delivered
<!-- Every spec scenario and decision from the approved plan. Status is done, changed or dropped; one line of reason for anything but done. Deviations from the plan's decisions get their own row. -->

| Item | Status | Note |
|---|---|---|
| <scenario or decision> | done | |

## Changes
<!-- One line at the top for anything the reviewer must not miss: breaking change, backfill, behaviour that differs from the ticket wording. Then one ```flowmap layer map of the change (format: scripts/flowmap.py). `lanes:` are the slices the change touches, in the profile's names and in request order (API before Application before Domain before Infrastructure); `rows:` are the services, or the journeys when one service has two. A `node` is a component on the path (resolver, handler, entity method, repository, consumer, policy), with its `file`; status and the Before / After views come from git, so write `status:` only when a node is a symbol inside a file (a deleted method in a modified file) or untouched context (`status: context`, no file needed). A `test` node names the test file and the node it `covers:`, or `status: missing` for a gap the review calls out. Edges: `a -> b` for a call, `a ~> b` for an event or message, `: label` for what crosses it, a `before:` prefix for a path that only existed on the base branch. Sixteen nodes at most: the path a request takes, not every file. Then, still before the first ###, one fence per example captioned `@<node id> <label>`: for an API node the query or request, its variables and the response; for a table node a ```record row (`column | value | note` per line) and the migration; for an event node the message payload. Write an example only when it comes from the schema, the migration, the contract or a QA capture in this review; otherwise leave it out. Then per service: ### ServiceName, a Slice / File / Change table (slices: Domain, Application, Infrastructure, API, Tests; anything else takes the nearest slice, so identity policies, infrastructure as code, workflows and config are Infrastructure). File is the repo-relative path in backticks, or a unique tail of it; the builder links it to that file's full diff, pulled from git and appended collapsed at the end of the section. Then the load-bearing hunks as #### title followed by a ```diff fence. At most eight hunks across the whole review; each under 60 lines. -->

```flowmap
lanes: <API>, <Application>, <Domain>, <Infrastructure>
rows: <ServiceName>

node <entry>: <Resolver or endpoint>
  lane: <API>
  file: <repo-relative path>
  kind: api

node <rule>: <Entity.Method>
  lane: <Domain>
  file: <repo-relative path>

node <store>: <Repository>
  lane: <Infrastructure>
  file: <repo-relative path>
  kind: data

test <rule-tests>: <TestClass>
  covers: <rule>
  file: <repo-relative test path>

<entry> -> <rule>
<entry> -> <store>: <what crosses>
```

```graphql @<entry> Query
<the query or request a client sends>
```

```record @<store> Example row · <table>
<Column> | <value> | <what changed>
```

### <ServiceName>
| Slice | File | Change |
|---|---|---|
| Domain | `<repo-relative path>` | <one line> |

#### <hunk title: what this hunk decides>
```diff
- old
+ new
```

## Contracts and coordination
<!-- Only what another team or another PR has to move for. The rows are illustrative: drop the ones that do not apply and add what does (tenants, client apps, feature flags). "None." rows are fine when the reader would otherwise wonder. -->

| Concern | Change | Action |
|---|---|---|
| GraphQL schema | <SDL delta or none> | <snapshot regenerated, FE informed> |
| Events | <new event, topic mapping, centralus mirror> | |
| Storage | <containers, tfvars> | <terraform PR> |
| Config | <App Configuration keys per environment> | |
| Migrations | | |
| Client apps | <web or mobile change this depends on> | |
| Type-name collisions | checked against <services> | |

## Findings
<!-- Code review findings from the reviewer sweep and the CLAUDE.md rules check. Status: fixed, accepted (with the reason in Note), or open. Open rows become accept/fix radios in the decision form. -->

| Severity | Location | Finding | Status | Note |
|---|---|---|---|---|
| high | `<path>:<line>` | <one sentence> | fixed | |

## QA report
<!-- Same structure the test skill posts to the work item. Environment and date line, then one #### per behaviour verified, tagged Acceptance test or Manual test with Pass, Fail or Blocked, a gherkin fence, an Evidence line, and a Classification line (regression | pre-existing bug | environment issue | not run) for anything but Pass. After the Evidence line, the proof that decided the result: an http fence for an API call (the request as sent, then the response from its status line; the page splits them into two panes and indents JSON), ![caption](evidence/<file>.png) for a screenshot, ![caption](evidence/<file>.webm) for a video, a sql or text fence for a query and its rows, never a markdown table. Each fence's caption (the words after the language) and each image or video caption repeats the gherkin step it proves, case and spacing are ignored; a whole-run video may take the scenario title instead. Fences fold into their step; screenshots and videos show in a grid under the steps. Media files live in evidence/ beside this file and publish next to the page. Credentials become <redacted>. At most ten images and three videos, 15 MB a file. Unit and integration suites are not QA and do not appear. If nothing was run, open with **No QA run.** and put every criterion under Not covered instead of inventing a Blocked row. End with the summary table and Not covered. -->

**Environment:** <qa environment / local> | **Date:** <YYYY-MM-DD> | **Test users:** <emails>

#### <Scenario title> `Acceptance test` **Pass**
```gherkin
Given <persona and precondition>
When <action>
Then <observed outcome>
```
Evidence: <one line>
```http When <action>
POST /api/<resource>
Authorization: Bearer <redacted>
Content-Type: application/json

{"<field>": "<value>"}

HTTP/1.1 201 Created
{"id": "<id>"}
```
![Then <observed outcome>](evidence/<file>.png)

| Scenario | Type | Env | Result |
|---|---|---|---|
| | Acceptance | sand | Pass |

**Not covered:** <behaviour related to the change that was not tested and why>

## Rollout
<!-- Ordered checklist, up to eight items, ticks persist on the page. Terraform first, config flags, stacked PR order, migrations, labels, hand-off. -->

- [ ] <step>

## Decision
<!-- Your recommendation in one or two sentences. The approve / request-changes form is added by the builder. -->

## Walkthrough
<!-- Only when the profile's optional.walkthrough is true; otherwise delete this section. A narrated tour the page plays from a button under the header: it scrolls to each scene's target, highlights it, animates a flowmap box's edges, and plays the line, recorded with Kokoro by scripts/narrate.py (captions always show). Up to eight numbered scenes, each a backticked target then one spoken line of at most 45 words, 220 words in all. Targets: a section name (`Verdict`), a row or heading inside one (`Findings > text in that row`), or a flowmap node (`@node-id`). Write for the ear: plain sentences, numbers as words ("ten of eleven", not 10/11), no backticks, links or markdown. Every fact must already be on the page and agree with it; the walkthrough adds no claims. Order it as the reviewer would read: verdict, the change on the map, open findings, QA, rollout, recommendation. -->

1. `Verdict` <the verdict in one spoken sentence, and the one number that matters>
2. `@<node id>` <what changed at this box and why the reviewer should care>
3. `Findings > <text in the open finding's row>` <the open finding and what it asks of the reviewer>
4. `Decision` <the recommendation>
