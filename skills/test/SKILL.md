---
name: test
description: Run the Test stage for a branch: the build and the unit and integration suites first, then the approved plan's acceptance scenarios against the profile's QA environment, opening the draft PR and applying the deploy label when that environment needs one, and write a BDD-format QA report of what was actually tested, covering acceptance runs and manual checks and never unit or integration suites, posted where the profile's qa.evidence says. Use whenever the user says "test", "run the scenarios", "qa", "qa report", "write up the testing", "document what we tested", "/qa-report", or when the kit's pipeline reaches the Test stage. Not for a bare "dotnet test" run with nothing to report. Also produces pre-hand-off QA notes, testing guidance written before anyone tests, covering what changed, how to test it per persona, test data and accounts, edge cases, out of scope, and environment or flag setup. Use notes mode whenever the user says "qa notes", "test notes", "notes for QA", or passes the literal argument "notes".
---

# Test

This skill has two modes. Default mode runs the Test stage and writes a report of what
was actually tested and what happened, not what should be tested next; it exists so a QA owner or a reviewer
can trust a Pass without re-running it themselves, and so a Fail carries enough to
decide whether it blocks anything. Notes mode writes the opposite direction: testing
guidance for someone who has not seen the change yet, written before testing happens.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin
root is two levels above it; adapters live at `<plugin root>/adapters/`.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/kit_profile.py"`. It decides:

- `qa.evidence`: where the report or the notes go after approval: `work-item` (the
  tracker adapter), `pr-comment` (the scm adapter), or `none` (print only, nowhere to
  send it).
- `qa.owner`: in notes mode, who the notes are for. `qa-team` posts them for someone
  else to act on; `self` and `none` mean the author is the one testing, so the notes
  are printed rather than handed off.
- `tracker` / `scm`: which adapter's posting steps to follow.
  Read `adapters/tracker/<tracker>.md` or `adapters/scm/<scm>.md`.
- `testing.acceptance`: the tool that produced any automated run (Reqnroll, SpecFlow,
  or none), named in the report's evidence lines where it matters.
- `artifacts`: whether to publish a rendered page at all.
- `pipeline.qa`: a project command that replaces the scenario run in step 2 when set.
- `qa.environment`, `qa.deploy_label`, `scm`: where the scenarios run and how the
  branch gets there. Read `adapters/qa/<qa.owner>.md` and `adapters/scm/<scm>.md`.
- `stack.local_run`: how to start the system when `qa.environment` is `local`.
- `optional.jev`: when true, failing tests are bucketed with `jev_classify` before any
  fixing, and the QA report's Classification column comes from the same call. See
  `docs/jev.md`. Skipped, never failed, when the MCP is not loaded.

## Default mode: run and report

1. **Run the suites, then the scenarios.** `dotnet build`, then `dotnet test` on the
   solutions the branch touches; a red suite stops here. Then run the approved plan's
   Specs (`plans/<id>-<slug>/plan.md`) the way `adapters/qa/<qa.owner>.md` says, or
   `pipeline.qa` when set. When `qa.environment` is not `local`, push the branch, open
   the draft PR through the scm adapter if none exists and apply `qa.deploy_label`, then
   wait for the deployment before running. Fix failures on the branch and rerun until
   green, unless a fix would change the ticket's scope. With `optional.jev`, bucket the
   failures first. Load `jev_classify` with one item per failing test or scenario: the
   name plus the assertion message, under 2000 characters. Pass the plan's Requirement
   and a one-line summary of the change as `context`. The classes: `real_regression`
   and `assertion_changed_by_refactor` (fix), `flaky_known` (rerun once, then treat as
   a regression), `environment` (follow `adapters/stack/local_run.md` "Common issues")
   and `manual_review` (read it yourself). Write `test` to the pipeline
   state file as `{"done": true, "at": "<ISO time>", "note": "<n> scenarios pass"}`.
2. **Check for an existing review page first.** If this session already produced a
   review artifact (the kit's review skill) that contains a QA section, copy that
   section verbatim into this report instead of rewriting it; the two must never
   diverge. Otherwise build the report from scratch in this step.
3. **Gather what was tested**, from the conversation or from what the user describes.
   For each distinct behaviour verified, capture: the persona and action as
   Given/When/Then; whether it was an **Acceptance test** (an automated run against a
   real environment) or a **Manual test** (a person's own steps, such as API calls,
   browser steps, or direct inspection of a provider or data store); the environment;
   the outcome,
   Pass, Fail or Blocked, with one line of evidence; and, for anything but Pass, whether
   it is a regression, a pre-existing bug, an environment issue, or simply not run. The
   Jev buckets from step 1 map straight onto that column: `real_regression` and
   `assertion_changed_by_refactor` are a regression, `flaky_known` that failed twice
   is a regression, `environment` is an environment issue; `manual_review` means you
   decide and say so in the Evidence line.
   **Capture the proof as you go**, per step, wherever it decided the result. An API
   call is the request and response (`curl -i` or the `.http` file's output). A
   screenshot is saved under `plans/<slug>/evidence/` with Playwright (the project's
   own, or `npx playwright screenshot <url> <file>`); the in-app browser cannot save
   to disk. A database check is the query and its rows. Redact every token, cookie,
   key and password to `<redacted>`, and trim bodies to the fields the step proves.
   **Unit and integration suites are never QA evidence.** If the only verification
   performed was an in-process test suite, say so and stop: there is nothing to report.
4. **Write the report** with this exact structure:

   ```markdown
   ## QA Report

   **Environment:** <sandbox / local / ...>  |  **Date:** <yyyy-mm-dd>  |  **Test users:** <accounts used>

   #### <Short scenario title>  `Acceptance test`  **Pass**
   ```gherkin
   Given <precondition, including the persona>
   When <action>
   Then <observed outcome>
   ```
   Evidence: <observed value, test-run count, transaction id>
   ```http When <action>
   <request, credentials as <redacted>, then the response>
   ```
   ![Then <observed outcome>](evidence/<file>.png)
   ```sql Then <observed outcome>
   <query, then its rows as text>
   ```

   #### <Short scenario title>  `Manual test`  **Fail**
   ...
   Evidence: ...
   Classification: <regression | pre-existing bug | environment issue | not run>

   ### Summary

   | Scenario | Type | Env | Result |
   |----------|------|-----|--------|

   ### Not covered
   <what was not tested and why>
   ```

   Put an API call in an `http` fence and a database check in a `sql` or `text`
   fence, never a markdown table. Each fence caption or image caption repeats the
   gherkin step it proves; case and spacing are ignored. The review page folds it into
   that step. Once the section is in a review, the review skill's `check_review.py`
   fails a caption that names no step, an unredacted credential, or over ten images.
   When nothing was run this session, open with **No QA run.** and list every
   acceptance criterion under Not covered instead of inventing a scenario.
5. **Publish as an Artifact only when `artifacts` is true.** Load the `artifact-design`
   skill first, then render the same content as stat tiles (pass counts per type), a
   card per scenario with the Given/When/Then in a labelled column, and the caveats. Do
   not add findings or soften an outcome that the markdown does not have.
6. **Ask for approval.** Show the report text (and the artifact link if one exists) and
   ask whether to post it. Do not post before a clear yes.
7. **Post per `qa.evidence`** the way the shared posting step below describes.

## Notes mode: pre-hand-off testing notes

Triggered by "qa notes", "test notes", "notes for QA", or the literal argument
`notes`. These notes tell someone who did not write the code how to test it: what
changed, what to click or call in what order, which accounts and data to use, and
where the edges of the change are, written before testing happens.

1. **Find the source material.** If an approved plan exists at
   `plans/<id>-<slug>/plan.md` (the kit's plan skill), derive the notes from its Specs
   section: the scenarios there are exactly the behaviours to test. With no plan,
   derive the notes from the diff instead, using `git diff <base>...HEAD`, and read the
   changed files well enough to describe user-facing behaviour, not implementation.
2. **Write the notes** covering:
   - **What changed**: a short bullet list in product terms, one line per user-facing
     behaviour. No class names, no file paths, no architecture.
   - **How to test it**: numbered steps per persona (for example "as an admin user",
     "as a freemium member"), each step an action and an expected result.
   - **Test data and accounts**: the concrete accounts, plans, or records needed to
     reach each scenario, named specifically enough to reuse them without guessing.
   - **Edge cases**: the boundary conditions the change introduces or touches (empty
     states, limits, concurrent actions, already-in-progress flows).
   - **Out of scope**: what looks related but was not changed, so QA does not spend
     time re-verifying it or filing it as a gap.
   - **Environment and feature flags**: which environment to test against and any flag
     that must be on (or off) for the change to be reachable.
3. **Ask before posting.** Show the notes in full and ask whether to add them. Do not
   post before a clear yes.
4. **Post per `qa.evidence`** the way the shared posting step below describes, in place
   of the report text. With `qa.owner: self` or `qa.owner: none`, there is no one to
   hand off to: print the notes and say plainly that they were not posted anywhere,
   since the author is the one testing.
5. **Confirm completion** with a link to wherever the notes landed, or, if nothing was
   posted, a one-line note of where the notes are (printed above, or saved to a file the
   user named).

## Posting (both modes)

Post per `qa.evidence`. `work-item`: follow the tracker adapter's "Post the QA report"
section (for the Azure Boards form this is a markdown comment via the REST API, never
`--discussion`, since that stores plain text as escaped HTML). `pr-comment`: post
through the scm adapter as a plain PR comment (for the GitHub form, `gh pr comment
<number> --body-file report.md`). `none`: print only, nothing to send. Evidence
fences post as plain text under their scenario. Screenshots stay on the review page:
replace each image line with its caption in plain text before posting. **Never change
the work item's or PR's state from this skill, in either mode.**

## Traps

- Plain ASCII only, `--` instead of em dashes, no emoji: some trackers garble
  non-ASCII characters.
- No bare PR numbers anywhere in the text. A tracker that auto-links `#1234` may resolve
  it to a work item or the wrong item, never reliably to the intended PR.
- No artifact link in the posted comment. Artifacts are private to the author's
  account, so a link in the tracker or PR is a dead end for the reader.
- A scenario that was not run is Not covered, never Pass. Omitting it instead of naming
  it looks like coverage that never happened.
- One scenario per behaviour, not per underlying check: a forty-test acceptance suite is
  one entry with the pass/fail count as evidence.
- Notes mode is written for QA, not for developers: no class names, no mention of
  aggregates or grains, no architecture. If a sentence needs an implementation detail
  to make sense, rephrase it around the user-facing behaviour instead.
- In notes mode, a plan's Specs section is the source of truth when one exists; do not
  re-derive scenarios from the diff in that case, since the two can drift apart.
- In notes mode, do not invent edge cases the change does not actually touch; "Out of
  scope" exists so QA does not have to guess which ones matter.

## Files

None. This skill has no scripts or templates of its own; rendering, when it runs, uses
the same page shape as the kit's review skill. The report structure above is also what
the review page's QA report section carries, so the two never diverge.
