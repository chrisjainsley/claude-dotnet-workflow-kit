---
name: qa-report
description: Generate a BDD-format QA report of what was tested this session, covering acceptance runs against a real environment and manual checks and never unit or integration suites, then post it where the profile's qa.evidence says. Use whenever the user says "qa report", "write up the testing", "document what we tested", or wants a test summary after running acceptance tests or manual verification.
---

# QA report

This report says what was actually tested and what happened, not what should be tested
next. It exists so a QA owner or a reviewer can trust a Pass without re-running it
themselves, and so a Fail carries enough to decide whether it blocks anything.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin
root is two levels above it; adapters live at `<plugin root>/adapters/`.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/profile.py"`. It decides:

- `qa.evidence`: where the report goes after approval: `work-item` (the tracker
  adapter), `pr-comment` (the scm adapter), or `none` (print only, nowhere to send it).
- `tracker` / `scm`: which adapter's posting steps to follow.
  Read `adapters/tracker/<tracker>.md` or `adapters/scm/<scm>.md`.
- `testing.acceptance`: the tool that produced any automated run (Reqnroll, SpecFlow,
  or none), named in the report's evidence lines where it matters.
- `artifacts`: whether to publish a rendered page at all.

## Workflow

1. **Check for an existing review page first.** If this session already produced a
   review artifact (the kit's review skill) that contains a QA section, copy that
   section verbatim into this report instead of rewriting it; the two must never
   diverge. Otherwise build the report from scratch in this step.
2. **Gather what was tested**, from the conversation or from what the user describes.
   For each distinct behaviour verified, capture: the persona and action as
   Given/When/Then; whether it was an **Acceptance test** (an automated run against a
   real environment) or a **Manual test** (a person's own steps, such as API calls,
   browser steps, or direct inspection of a provider or data store); the environment;
   the outcome,
   Pass, Fail or Blocked, with one line of evidence; and, for anything but Pass, whether
   it is a regression, a pre-existing bug, an environment issue, or simply not run.
   **Unit and integration suites are never QA evidence.** If the only verification
   performed was an in-process test suite, say so and stop: there is nothing to report.
3. **Write the report** with this exact structure:

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

   When nothing was run this session, open with **No QA run.** and list every
   acceptance criterion under Not covered instead of inventing a scenario.
4. **Publish as an Artifact only when `artifacts` is true.** Load the `artifact-design`
   skill first, then render the same content as stat tiles (pass counts per type), a
   card per scenario with the Given/When/Then in a labelled column, and the caveats. Do
   not add findings or soften an outcome that the markdown does not have.
5. **Ask for approval.** Show the report text (and the artifact link if one exists) and
   ask whether to post it. Do not post before a clear yes.
6. **Post per `qa.evidence`.** `work-item`: follow the tracker adapter's "Post the QA
   report" section (for the Azure Boards form this is a markdown comment via the REST
   API, never `--discussion`, since that stores plain text as escaped HTML). `pr-comment`:
   post through the scm adapter as a plain PR comment (for the GitHub form,
   `gh pr comment <number> --body-file report.md`). `none`: print only, nothing to send.
   **Never change the work item's or PR's state from this report.**

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

## Files

None. This skill has no scripts or templates of its own; rendering, when it runs, uses
the same page shape as the kit's review skill.
