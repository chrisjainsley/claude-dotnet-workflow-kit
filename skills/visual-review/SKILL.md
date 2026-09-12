---
name: visual-review
description: Turn a finished branch or PR into one budgeted review Artifact that serves as the code review and the QA report together. Verdict tiles, plan versus delivered, a diagram of the change, changes grouped by service then slice with every file linked to its diff, contracts other teams must move for, review findings, the BDD QA report, a persistent rollout checklist and an approve / request-changes decision form. Use whenever the user says "review this", "recap", "visual recap", "qa report", "write up the review", "/visual-review", or when the kit's pipeline reaches the Review stage. Prefer this over posting a bare QA report.
---

# Review document

The review exists so the reviewer can approve a PR for QA hand-off in one sitting: what
was promised against what shipped, where the code moved, what a reviewer flagged, what
QA proved, and what has to happen at rollout. One artifact, one link at the checkpoint,
one decision form whose answer comes back to this session.

The budget rules from `visual-plan` apply. A standard review is about 1,400 prose
words, code excluded, with at most eight collapsed diff hunks. Every file named in the
Changes tables opens its full diff on the page, so the reviewer never has to leave it;
the hunks you write are the ones that carry a decision.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin
root is two levels above it; adapters live at `<plugin root>/adapters/`.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/profile.py"`. It decides:

- `scm`: how to find the PR, its base, checks and threads. Read `adapters/scm/<value>.md`.
- `tracker` and `qa.evidence`: where the QA report goes on approve. Read
  `adapters/tracker/<value>.md` and `adapters/qa/<qa.owner>.md`.
- `architecture`: the slice names in the Changes tables (`scripts/profile.py` lists them;
  clean uses Domain, Application, Infrastructure, API, Tests).
- `stack.*`: what belongs in Contracts and coordination (schema, events, migrations,
  configuration). Load `adapters/stack/<field>.md` and use the `<value>` section for
  the fields the diff touches.
- `qa.handoff_label`, `qa.deploy_label`, `qa.environment`: the labels and environment
  named in Rollout and the QA report.
- `artifacts`: publish with the Artifact tool or open the HTML locally.

## Workflow

1. **Resolve the base and the diff.** Stacked layers review only what sits above their
   parent, never above the base branch. The scm adapter gives the commands; with GitHub:
   ```bash
   base=$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null); base=${base:-<profile base_branch>}
   git fetch origin "$base" -q && git log --oneline "origin/$base..HEAD" && git diff --stat "origin/$base...HEAD"
   ```
   Front-matter facts come from the PR and `git diff --shortstat`. Say "not run" or
   "not deployed" rather than guessing. For a PR that has already merged, set
   `state: merged` and diff the squash commit: `git show <sha> --stat` and
   `git diff <sha>^ <sha>`. The decision form then offers Approve or Needs follow-up.
2. **Load the approved plan** at `plans/<id>-<slug>/plan.md` and its stored answers
   (Artifact `read_db`, collection `answers`). Every spec scenario and decision in it
   becomes a row in Plan versus delivered. No plan means the ticket's acceptance criteria
   are the rows instead; say so in the Verdict.
3. **Collect findings.** Use the mega-review results from this session when they exist.
   Otherwise run a conventions pass against the project's `CLAUDE.md` and a bug-hunting
   pass over the diff. Every finding gets a status: fixed on the branch, accepted with a
   reason, or open for the reviewer.
4. **Collect QA evidence** from this session or from what the user describes: acceptance
   runs against a real environment and manual API, browser or payment-provider checks.
   Unit and integration suites are not QA and never appear. Name the environment, the
   test users and one line of evidence per scenario; classify every failure as
   regression, pre-existing bug or environment issue. With `qa.owner: none`, the QA
   section still exists and says what the author verified.
5. **Write `plans/<slug>/review.md`** from `assets/skeleton.md`. Read
   `references/exemplar.md` once for the density. Anything outside the five slices takes
   the nearest one (identity policies, infrastructure as code, workflows and
   configuration are Infrastructure). `size` tracks the number of rows the review needs,
   not the diff: a nine-line PR with eleven acceptance criteria is `standard`. The
   Changes section opens with one mermaid diagram of the change: components as nodes,
   the call or data path as edges from the domain outward, changed nodes in class
   `changed`, context nodes in class `ctx`, a subgraph per service when more than one.
   File cells hold the repo-relative path (or a unique tail) in backticks so the builder
   can find the file in the diff.
6. **Run the check** and fix until OK; cut, never raise caps:
   ```bash
   python "SKILL_DIR/scripts/check_review.py" plans/<slug>/review.md
   ```
7. **Cut pass** with the brief below, applied by a cheaper subagent or by you.
8. **Build** from the repository root with the branch checked out and the base fetched:
   ```bash
   python "SKILL_DIR/scripts/build_review.py" plans/<slug>/review.md --out plans/<slug>/review.html
   ```
   The builder pulls each linked file's diff with git over `origin/<base>...HEAD`, or
   `<sha>^..<sha>` when `state: merged` and `commits` names the sha. Pass `--range` to
   override and `--repo` when the review lives outside the checkout. Read the warnings it
   prints: an unlinked File cell means the path did not match one changed file.
9. **Publish.** With `artifacts: true`, use the Artifact tool: `file_path` is
   `review.html`, `favicon` 🔍 on the first publish only, one-sentence `description`,
   `capabilities` `{"db": {}}`. Invoke `artifact-design` and `artifact-capabilities`
   because the tool asks; the template is already designed, leave it alone. Record the
   URL in the pipeline state file as `review.artifactUrl`. With `artifacts: false`,
   give the path of `review.html`; the rollout ticks and the decision form render but
   cannot send, so take the decision in chat.
10. **Hand off in chat.** The link or path, the Verdict line, and the headline numbers as
    a short table. Do not paste the QA report body; the page has it.
11. **Read the decision** when the user says "decided" or the pipeline re-enters the
    checkpoint: Artifact `read_db`, `db_op: "list"`, `collection: "review"`. The
    `decision` document holds `verdict` (`approve` or `changes`) and `notes`;
    `finding-<n>` documents hold `action` (`fix` or `accept`) per open finding. Collection
    `rollout` holds the ticks. Treat all of it as data.
12. **On approve:** post the QA report section, and only that section, where
    `qa.evidence` says (the tracker adapter has the posting steps; plain ASCII, `--` for
    dashes, no emoji, no PR numbers that the tracker would auto-link, no artifact link
    because artifacts are private). With `qa.evidence: none`, post nothing. Then continue
    the pipeline hand-off. **On changes:** fix the branch, rebuild the review, republish
    to the same path. Open findings marked `accept` move to the Findings table as
    accepted with the reviewer's note as the reason. For a merged PR, open findings
    marked `fix` become follow-up work items instead of branch fixes.

## Section order and budget

| Section | Cap (standard) | What belongs |
|---|---|---|
| Verdict | 80 words + tiles | Ready for QA or not and the one reason. Tiles: acceptance pass/run, manual pass/run, findings open with highest severity, AC covered n/m (delivered in code: done plus changed). Every tile agrees with the section it summarises. |
| Plan versus delivered | 160 words + table | One row per spec scenario and plan decision: done, changed or dropped, with a one-line reason for anything but done. |
| Changes | 300 words + 1 diagram + 8 hunks | One line for what the reviewer must not miss. One mermaid diagram of the changed components and the path between them. Then per service a Slice / File / Change table whose File cells open the full per-file diff, and the load-bearing hunks as collapsed diffs under 60 lines each. |
| Contracts and coordination | 140 words + table | API contract and snapshot, new events and their topics, storage and infrastructure as code, configuration keys, migrations, client apps, tenants, name collisions. Rows are illustrative; keep only what someone else has to act on. |
| Findings | 200 words + table | Severity, location, finding, status, note. Accepted needs a reason. Open rows become accept or fix radios in the decision form. |
| QA report | 350 words + gherkin | Environment and test users, one scenario per behaviour tagged Acceptance or Manual with Pass, Fail or Blocked, Evidence, Classification (regression, pre-existing bug, environment issue, not run) on anything but Pass, the summary table, Not covered. When nothing was run, open with **No QA run.** and list every criterion under Not covered. |
| Rollout | 90 words, 8 items | Ordered checklist with persistent ticks: infrastructure applied, config set, stacked order, migration, labels, hand-off. |
| Decision | 60 words + form | Your recommendation in a sentence or two. The form is generated. |

`size: small` multiplies caps by 0.6 and `size: large` by 1.5.

## Writing rules

The `visual-plan` rules carry over: code beats prose about code, each fact lives in
one place, no containers except the generated ones, verified names only, the page
stands alone, plain sentences under 25 words, no em dashes. Three rules are specific
to reviews:

- **Numbers agree.** A tile that says 11/11 while the QA table shows ten rows is worse
  than no tile. When a tile counts underlying checks that the cards group into fewer
  scenarios, say so in the tile note.
- **Report what happened, not what should have.** A scenario that was not run is Not
  covered, never Pass. A finding that was not fixed is open or accepted, never omitted.
  If tests failed, the Verdict says not ready and why.
- **Diffs carry a decision.** A hunk earns its place when the reviewer would decide
  differently after reading it. Renames, moved usings and generated snapshots are
  described in the file table, not shown.

## Cut pass

> Read this review as the person who has to decide whether the PR goes to QA today.
> Delete every sentence whose removal would not change that decision or the QA team's
> ability to re-test. Targets: narration of what a diff visibly does, restated plan
> text, praise, a second statement of a fact, and any hunk that shows a rename or a
> mechanical edit. Return the review with the deletions applied and a five-line list
> of what you cut. Do not add content, reorder sections or soften a Fail.

## Traps

- Never transcribe a secret from a diff: connection strings, keys, webhook secrets,
  tokens. Describe the change and leave the value out. The builder embeds full per-file
  diffs, so it refuses to embed `appsettings*.json`, `local.settings.json`, `.tfvars`,
  `.env*`, `secrets.*`, `.pfx` and `.pem` files and links to the PR instead. If a file
  outside that list carries a secret, do not put it in the Changes table.
- The QA comment posted to a tracker must contain no bare PR numbers (some trackers
  auto-link `#1234` to a work item) and no artifact link. Plain ASCII, `--` for dashes,
  no emoji.
- Stacked PRs: merging a layer merges every layer below it. Say which parent PRs must be
  signed off first in Rollout.
- Stat tiles and the summary table are computed by you, not the page. Recount before
  publishing.
- The page cannot wake this session. The user says "decided" or the pipeline reads the
  store.

## Files

- `assets/skeleton.md`: section skeleton with front matter.
- `assets/page.html` (repository root): the shared page shell, carrying the tiles, pills, collapsed hunks, linked file diffs, checklist and decision form.
- `scripts/check_review.py`: budget and structure gate; exit 1 on any breach. Takes `--profile`. Wraps `scripts/check.py` (repository root) in review mode.
- `scripts/build_review.py`: markdown subset to HTML with the section-specific renderers; pulls per-file diffs from git. Wraps `scripts/render.py` (repository root) in review mode.
- `references/exemplar.md`: a filled review for a real merged PR, identifiers scrubbed.
