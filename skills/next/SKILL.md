---
name: next
description: The user's automated work-item delivery pipeline. Assesses where the current branch and work item sit in the standard workflow (start ticket, plan, execute, review, draft PR, resolve comments, QA, review page, publish and hand off), prints a status table, then runs stage after stage without asking for input, stopping only at the review checkpoint or on a big blocker. Use whenever the user says "next", "what's next", "move this along", "keep going", "continue the ticket", or "run the pipeline". "/next status" prints the table only, with no execution.
---

# Next: work-item pipeline driver

Drive a work item through the profile's delivery pipeline without needing input at each stage. The goal of a run is the review checkpoint: a QA'd draft PR and one review artifact carrying the recap, the findings and the draft QA report, presented together for one decision. Nothing is published until the user signs off there.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin root is two levels above it; adapters live at `<plugin root>/adapters/`.

Every invocation:

1. **Assess** each stage from live signals plus the state file.
2. **Report** the status table.
3. **Run** stages one after another, re-assessing between them, until the checkpoint or a blocker stops the run; announce each with a one-liner and never ask permission mid-run.

`/next status` prints the table and the recommended next action without executing anything.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/kit_profile.py"`. It decides which adapter answers each stage:

- `tracker`, `tracker_project`: fetching, starting and updating the item; read `adapters/tracker/<value>.md`.
- `scm`: finding, drafting, checking and threading the PR; read `adapters/scm/<value>.md`.
- `base_branch`, `branch_pattern`: what stage 0 checks for and stage 4 targets.
- `qa.owner`, `qa.evidence`, `qa.handoff_label`, `qa.deploy_label`, `qa.environment`: who runs QA, where the report goes, and which labels and environment reach it; read `adapters/qa/<qa.owner>.md`.
- `testing.tdd`: whether stage 2 writes tests first.
- `pipeline.execute`, `pipeline.resolve_comments`, `pipeline.qa`: a project command that replaces the default for that stage, when set.
- `artifacts`: whether the plan and review pages publish, or only render locally with the decision taken in chat.
- `reviewers`, `optional.*`: which review passes stage 3 runs and which optional tooling exists.

If the profile resolves from defaults, say so and suggest `/dotnet-workflow-kit:setup` first.

## The pipeline

| # | Stage | How it's done | Done when |
|---|-------|----------------|-----------|
| 0 | Start ticket | `/dotnet-workflow-kit:start-ticket` | Branch matching `branch_pattern` exists, item active per the tracker adapter; with `tracker: none`, the branch alone is enough |
| 1 | Plan | `/dotnet-workflow-kit:visual-plan` | Plan page produced and the user has answered or approved it; state `plan.artifactUrl` |
| 2 | Execute | `pipeline.execute` when set, else implement the plan directly, tests first when `testing.tdd` is strict, one commit per plan layer | Commits exist on the branch beyond the base |
| 3 | Review | `/dotnet-workflow-kit:mega-review` | State `megaReview.done`; findings fixed or accepted |
| 4 | Draft PR | Scm adapter: draft against `base_branch` or the stacked parent, title from the ticket, body from the plan's Requirement and Specs, `qa.handoff_label` applied when `qa.owner` is `qa-team` | Draft PR open, checks green |
| 5 | Resolve comments | `pipeline.resolve_comments` when set, else the scm adapter's review-thread steps | 0 unresolved threads, checks green |
| 6 | QA | `pipeline.qa` when set, else the plan's Specs run manually per `adapters/qa/<qa.owner>.md`; `qa.deploy_label` applied when set, to reach `qa.environment`; fix and re-run | Scenarios pass; state `qa.done` |
| 7 | Review page | `/dotnet-workflow-kit:visual-review`, built after QA so it reflects the final diff; do not post to the tracker yet | State `review.artifactUrl` |
| 8 | Publish and hand off | Once approved: post the QA report per `qa.evidence`, mark the PR ready, apply `qa.handoff_label` if not set, move the item to the tracker's `tracker_states.qa_ready` state (or the adapter's default when blank); `qa.owner` self or none just marks it ready | State `review.decision`, `handoff.done` |

Bug-fixing for a mega-review finding or a QA failure is never its own row: the stage that found it stays not-done, with the finding or bug in its evidence column, and fixing it is the next action inside that stage.

## State file

Stages 1, 3, 6, 7 and 8 leave no reliable trace in git or the scm, so completion is tracked in a state file:

```
~/.claude/dotnet-workflow-kit/pipeline/<slug>.json
```

Key by the ticket id when the branch carries one, else the sanitized branch name. Shape:

```json
{
  "ticket": "PROJ-1234",
  "branch": "feat/PROJ-1234-add-thing",
  "stages": {
    "startTicket": { "done": true, "at": "2026-09-01T10:00:00Z" },
    "plan": { "done": true, "at": "2026-09-01T12:30:00Z", "artifactUrl": "" },
    "execute": { "done": true },
    "megaReview": { "done": true, "at": "2026-09-02T09:00:00Z", "note": "1 finding accepted" },
    "draftPr": { "done": true, "url": "" },
    "resolveComments": { "done": true },
    "qa": { "done": false, "at": "", "note": "" },
    "review": { "done": false, "artifactUrl": "", "decision": "" },
    "handoff": { "done": false }
  }
}
```

Update it right after completing a stage, including one that happened naturally in conversation without this skill being invoked. Live signals always win: if the file says no PR exists but the scm adapter finds one, trust the scm and backfill the file. Manual overrides: "/next done <stage>" marks a stage complete, "/next reset" clears the file.

## The status table

```
PROJ-1234 - Add thing (feat/PROJ-1234-add-thing)

| # | Stage | Status | Evidence |
|---|-------|--------|----------|
| 0 | Start ticket | done | branch + active |
| 1 | Plan | done | plan approved 1 Sep |
| 2 | Execute | done | 4 commits ahead of base |
| 3 | Review | done | mega-review clean |
| 4 | Draft PR | done | #42 draft, checks green |
| 5 | Comments | in progress | 2 unresolved threads |
| 6 | QA | todo | |
| 7 | Review page | todo | |
| 8 | Handoff | todo | waiting on stage 7 |

Next: resolve comments on #42, 2 unresolved threads.
```

Statuses are plain words: done, in progress, todo, blocked. Keep evidence to a count, a date, a PR number or one clause. The "Next" line names the earliest stage that is not done; unless this is "/next status", it starts right after the table prints.

## Running without input

Invoking the pipeline is standing approval for everything up to the checkpoint, including commits, pushing the branch, opening the draft PR, and applying `qa.deploy_label`. A draft PR is a safe intermediate: nothing is announced to anyone. Never pause for a per-stage confirmation; announce each stage with a one-liner and report a one-line delta between stages, not the full table.

Mega-review findings get fixed, not queued for permission, unless a fix would change the ticket's scope. QA failures likewise: fix and re-run until green.

Stop only for a big blocker, something the user genuinely has to decide or that cannot be self-served:

- Failing CI that is not this branch's fault: the failing job touches files outside the diff, or the same job is red on the base branch too. Retry once silently; if it stays red against unrelated infrastructure, that is the blocker.
- A merge conflict with the base branch that is not mechanically resolvable.
- A missing or default-sourced profile: suggest `/dotnet-workflow-kit:setup` rather than guessing labels or an environment.
- A stacked parent not yet merged when stage 8 is reached.
- A QA failure whose fix changes scope or touches infrastructure, or a review finding that contradicts the ticket's acceptance criteria.
- Missing credentials or access.

When blocked, print the table, state the blocker and a recommended resolution in two or three sentences, and stop.

## The checkpoint

When stages 0 through 7 are done, present everything in one message and stop:

1. The draft PR link and a one-paragraph summary of the change.
2. The review artifact link, its Verdict line, and the headline numbers as a small table (acceptance, manual QA, open findings, criteria covered). Do not paste the QA report body.
3. The final status table.

The review link goes in the checkpoint message itself as a plain URL; a link only inside a subagent's transcript does not count as delivered.

Then wait. When the user says "decided" or invokes the pipeline again, read the decision with the Artifact tool: `read_db`, `db_op: "list"`, `collection: "review"`, url from `review.artifactUrl`. The `decision` document carries `verdict` (`approve` or `changes`) and `notes`; `finding-<n>` documents carry `action` (`fix` or `accept`) per open finding. Approve continues to stage 8. Changes returns to stage 2 with the notes and the per-finding fix or accept choices, then rebuilds and republishes the review to the same URL before re-presenting only what changed. With `artifacts: false`, take the verdict in chat instead.

## Drafting the PR (stage 4)

Push the branch, then let the scm adapter's steps create the draft: title from the ticket, body from the plan's Requirement and Specs, base set to `base_branch` or the stacked parent. Apply `qa.handoff_label` when `qa.owner` is `qa-team`. The PR stays a draft until the checkpoint is approved; marking it ready is a stage 8 action.

## House rules

- Never enter Claude's plan mode for this pipeline; the plan stage is a published page, not a mode.
- Never remove `qa.handoff_label`, and never change the work item's state from a QA comment; only the tracker adapter's own steps do that.
- Commit only when the current stage requires it, saying so if a commit happens outside stage 2.
- Use the profile's own label and environment names throughout, never a hardcoded literal.
- Print the plan and review artifact links in the main reply, not only inside a subagent's transcript.
- Investigate and re-run CI failures silently; report findings in chat, not as PR status comments.
- New commits during stage 5 or 6 fix feedback only, force-push-with-lease reserved for a rewritten stacked layer.
- A branch conflicting with the base pre-empts whatever stage was next.

## Traps

- A review or QA marker older than the branch's latest commit is stale, not done; downgrade it and redo the stage rather than trust a marker describing an earlier diff.
- Stacked layers: a stage measures only the work above its own parent, never above the ultimate base, and merging a layer merges everything below it, so the checkpoint must name the parent PRs that need to clear QA first.
- With `artifacts: false`, the pages still render but cannot send a decision back to this session; take every decision in chat and still record it in the state file.
- The pages cannot wake this session on their own; only "answered" or "decided" from the user, or a fresh invocation, triggers a re-read of a stored decision.
