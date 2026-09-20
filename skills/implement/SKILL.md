---
name: implement
description: Implement an approved plan on the current branch, one commit per plan layer, tests first when the profile says so, then run the reviewer sweep (parallel bug-hunt and conventions reviewers plus any the profile enables), fix what it finds, clean up and verify the build and tests before anything is tested or reviewed. Use whenever the user says "implement", "implement the plan", "build it", "execute the plan", "mega review", "full review", "pre-PR check", or when the kit's pipeline reaches the Implement stage. Prefer this over ad-hoc coding once a plan page has been approved.
---

# Implement

This skill turns an approved plan into commits on the branch and leaves the branch
clean enough to test: the code, the tests the plan promised, and a reviewer sweep whose
findings are fixed before anyone else sees the diff.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin
root is two levels above it; adapters live at `<plugin root>/adapters/`.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/kit_profile.py"`. It decides:

- `pipeline.execute`: a project command that replaces the coding steps below when set.
  Run it, then continue from the sweep.
- `testing.tdd`: `strict` writes each layer's tests before its code; `encouraged` writes
  them in the same commit; `none` leaves the order to you.
- `testing.unit`, `testing.integration`, `testing.acceptance`: which frameworks the
  Tests section of the plan names, and what counts as the suite in verification.
- `architecture`: the layer order the plan follows and one commit each. Read
  `adapters/architecture/<value>.md`.
- `stack.*`: the conventions each layer's code should follow. Load
  `adapters/stack/<field>.md` for the fields the plan touches.
- `reviewers`, `optional.*`, `scm`, `base_branch`: what the sweep runs, and against
  which base. See `../review/sweep.md`.
- `optional.jev`: when true, the sweep scores the profile's `checks` with Jev and gates
  its verdict, and step 5 classifies open findings with `jev_classify`. See
  `docs/jev.md`. Skipped, never failed, when the MCP is not loaded.

If the profile resolves from defaults, say so and suggest `/dotnet-workflow-kit:setup`.

## Workflow

1. **Load the approved plan** at `plans/<id>-<slug>/plan.md` and its stored answers
   (Artifact `read_db`, collection `answers`, when the plan was published). Every
   answer is a settled decision. With no plan, stop and hand off to
   `/dotnet-workflow-kit:plan`; this skill does not design.
2. **Confirm the branch and a clean tree.** The branch should match the profile's
   `branch_pattern`; `git status --short` should be empty. A dirty tree means someone is
   mid-edit: list the files and ask before continuing.
3. **Walk the plan's layers in order**, one commit per layer that has a change
   (Domain, Application, Infrastructure, API, Tests for clean architecture; Slice,
   Persistence, Integration, Endpoint, Tests for vertical slices). For each layer:
   - With `testing.tdd: strict`, write the layer's tests from the plan's Tests table
     first, run them red, then write the code.
   - Write exactly what the plan's section names: the signatures, the load-bearing
     branch, the Infrastructure rows. Do not invent work a layer's "No change." rules
     out.
   - Build after each layer. Commit with a one-line message naming the layer and the
     ticket.
   With `pipeline.execute` set, run that command instead of this step.
4. **Write the acceptance scenarios** from the plan's Specs as a feature file when
   `testing.acceptance` is `reqnroll` or `specflow`, or as integration tests when it is
   `none`. They are the contract the Test stage runs.
5. **Run the reviewer sweep** from `../review/sweep.md`: parallel read-only reviewers,
   sequential cleanup, then verification on the cleaned tree. Fix every finding that
   does not change the ticket's scope and commit the fixes; a finding that would change
   scope is recorded as open for the reviewer. With `optional.jev`, load `jev_classify`
   and classify every finding in one call before fixing any, with the plan's
   Requirement and Specs as `context`, into `fixable_in_scope` (fix and commit),
   `changes_scope` (record open for the reviewer), `contradicts_acceptance` (the
   blocker below) and `manual_review` (read it and decide yourself). Read the `review`
   decisions yourself too; a classification is a hint about scope, not a verdict on
   the code.
6. **Write the pipeline state.** In `~/.claude/dotnet-workflow-kit/pipeline/<slug>.json`
   set `implement` to `{"done": true, "at": "<ISO time>", "commits": <n>}`; the sweep
   step has already written `sweep`.
7. **Report in chat:** commits made, the sweep verdict, findings fixed and open, and the
   verification result. Then hand off to `/dotnet-workflow-kit:test`, or back to the
   pipeline when it invoked this skill.

## Traps

- Never enter Claude's plan mode from this skill. The plan is the page; this skill
  builds it.
- Never push, open a PR or change tracker state here. Those are Test and Pull request
  stage actions in the pipeline.
- A plan question left unanswered is not yours to answer. Take the recommended option
  the page preselected and say so in the report.
- A sweep finding that contradicts the plan's acceptance criteria is a blocker, not a
  fix; stop and surface it.
- Commit only the work of the layer in hand; the sweep's cleanup gets its own commit so
  the layer commits stay readable.

## Files

None of its own. The reviewer sweep and its briefs live under `skills/review/`.
