---
name: next
description: The user's automated work-item delivery pipeline. Assesses where the current branch and work item sit in the standard workflow (start, plan, implement, test, review, pull request), prints a status table, then runs stage after stage without asking for input, stopping only at the plan gate, the review checkpoint or on a big blocker. Use whenever the user says "next", "what's next", "move this along", "keep going", "continue the ticket", or "run the pipeline". "/next status" prints the table only, with no execution.
---

# Next: work-item pipeline driver

Drive a work item through the profile's delivery pipeline without needing input at each stage. The goal of a run is the review checkpoint: a tested branch and one review artifact carrying the recap, the findings and the QA report, presented together for one decision. Nothing is published until the user signs off there, and the kit never merges: a person approves every merge.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin root is two levels above it; adapters live at `<plugin root>/adapters/`.

Every invocation:

1. **Assess** each stage from live signals plus the state file.
2. **Report** the status table.
3. **Run** stages one after another, re-assessing between them, until a gate or a blocker stops the run; announce each with a one-liner and never ask permission mid-run.

`/next status` prints the table and the recommended next action without executing anything.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/kit_profile.py"`. It decides which adapter answers each stage:

- `tracker`, `tracker_project`: fetching, starting and updating the item; read `adapters/tracker/<value>.md`.
- `scm`: finding, drafting, checking and threading the PR; read `adapters/scm/<value>.md`.
- `base_branch`, `branch_pattern`: what stage 0 checks for and stage 5 targets.
- `qa.owner`, `qa.evidence`, `qa.handoff_label`, `qa.deploy_label`, `qa.environment`: who runs QA, where the report goes, and which labels and environment reach it; read `adapters/qa/<qa.owner>.md`.
- `testing.tdd`: whether stage 2 writes tests first.
- `pipeline.execute`, `pipeline.resolve_comments`, `pipeline.qa`: a project command that replaces the default for that stage, when set.
- `artifacts`: whether the plan and review pages publish, or only render locally with the decision taken in chat.
- `reviewers`, `optional.*`: which review passes the sweep in stage 2 runs and which optional tooling exists.
- `stage_checks`: the team's own yes/no checks a stage must pass before it is marked done. See "Stage checks" below.
- `extra_stages`: the team's own stages, run between the built-in ones. See "Extra stages" below.
- `optional.jev`: when true, red CI jobs and review threads are classified with `jev_classify` before the pipeline acts on them, and thread bodies are screened with `jev_screen` first. See `docs/jev.md`. Every call is skipped, never failed, when the MCP is not loaded.

If the profile resolves from defaults, say so and suggest `/dotnet-workflow-kit:setup` first.

## The pipeline

| # | Stage | How it's done | Done when |
|---|-------|----------------|-----------|
| 0 | Start | `/dotnet-workflow-kit:start` | Branch matching `branch_pattern` exists, item active per the tracker adapter; with `tracker: none`, the branch alone is enough |
| 1 | Plan | `/dotnet-workflow-kit:plan` | Plan page produced and the user has approved it; state `plan.artifactUrl`, plus `plan.designUrl` when the plan made a Design canvas. **Gate: the user approves.** Approve continues straight to Implement in the same turn; Revise rebuilds the plan and stops at the gate again. |
| 2 | Implement | `/dotnet-workflow-kit:implement`, or `pipeline.execute` when set followed by the sweep | Commits exist on the branch beyond the base; state `sweep.commit` is HEAD with findings fixed or accepted |
| 3 | Test | `/dotnet-workflow-kit:test`, or `pipeline.qa` when set; the draft PR is opened and `qa.deploy_label` applied when `qa.environment` needs a deployment | Suites green, the plan's scenarios pass; state `test.done` |
| 4 | Review | `/dotnet-workflow-kit:review`, built after Test so it reflects the final diff; do not post to the tracker yet | State `review.artifactUrl` and `review.decision`. **Gate: the checkpoint.** |
| 5 | Pull request | Scm adapter: open the draft if Test did not, resolve threads (`pipeline.resolve_comments` when set), then once approved post the QA report per `qa.evidence`, mark the PR ready, apply `qa.handoff_label`, move the item to `tracker_states.qa_ready` (or the adapter's default) | 0 unresolved threads, checks green, PR ready; state `pullRequest.done`. A person merges. |

## Bug-fix runs

`/dotnet-workflow-kit:fix` starts a bug-fix run in place of Start and Plan. A state file with a `stages.repro` entry is one; build its order with `kit_profile.py --order --fix`. The Reproduce row replaces the Plan row. It is done when `stages.repro` is done and `plans/<id>-<slug>/plan.md` exists; until then the next action is `/dotnet-workflow-kit:fix`. There is no plan gate. Implement, Test and Review run as above, with two differences:

- Test also runs the regression area: the plan's Tests rows marked "regression area". A red one is a Test failure like any other.
- At the checkpoint, approve the review yourself when all of these hold: `stages.repro.outcome` is `reproduced`, the bug's scenario now passes, the suites and the regression area are green, no finding is open, and every stage check passed. Record `review.decision` as `approve` with the note "auto-approved: bug fix verified", and send one message that opens with the checkpoint's first line word for word, then gives the review link, its Verdict line and the note. Go straight on to stage 5 without waiting. When any of them fails, stop at the checkpoint as usual, and name the condition that failed in the summary paragraph. A bug that was never reproduced always stops here, since nothing showed the fix works.

Bug-fixing for a sweep finding or a Test failure is never its own row: the stage that found it stays not-done, with the finding or bug in its evidence column, and fixing it is the next action inside that stage.

## Extra stages

The profile's `extra_stages` add the team's own stages, each `{id, label, after, run, done_when, gate}`. `python "SKILL_DIR/../../scripts/kit_profile.py" --order` prints the full run order with each extra stage slotted after the stage it names; write that list to the state file's `order` on every run, adding `--fix` when `stages.repro` exists. An extra stage runs when the stage before it is done: run `run`, a slash command or a plain instruction, then answer `done_when`, a yes/no question, the way stage checks are answered below. Yes marks it done. No keeps it in progress, and fixing what the answer found is the next action inside it. With `gate: true`, stop after it is done and before the next stage, set `stages.<id>.waiting` to true, and clear it once the user replies. Record each as `stages.<id>`: `{"done", "at", "waiting", "note"}`. An extra stage gets a row in the status table, in run order.

## Stage checks

The profile's `stage_checks` add the team's own conditions to the Done-when column. Each stage key holds a list of `{id, prompt, on_fail}`. The keys are `start`, `plan`, `implement`, `test`, `review` and `pull_request`, plus `repro` for a bug-fix run. A `prompt` is a yes/no question that a yes answer satisfies. Run them when the built-in rule for a stage is met and before marking it done. For the plan and review stages, run them before presenting the page, never in place of the user's decision.

The evidence each stage is judged on:

| Stage | Evidence |
|---|---|
| start | the fetched ticket text and the branch name |
| repro | the repro evidence, the regression test's red run and `plan.md` |
| plan | `plan.md` and the stored answers |
| implement | the diff (`--range origin/<base>...HEAD`) and the sweep report |
| test | the raw build and test runner output and the QA report |
| review | `review.md` |
| pull_request | the PR body, `gh pr checks` output and the unresolved thread count |

Write the evidence that is not already a file to files beside the state file (`<slug>-<stage>-evidence.txt`), never into the checkout. With `optional.jev`, score them in one call:

```bash
python "<plugin root>/scripts/jev_checks.py" --stage <stage> --evidence <files> [--range "origin/$base...HEAD"] --out ~/.claude/dotnet-workflow-kit/pipeline/<slug>-<stage>-checks.json
```

A yes at or above `jev.flag_at` passes, between `jev.review_at` and `jev.flag_at` needs you to read the evidence and decide, and below `jev.review_at` fails. When the output says the evidence was trimmed, every check answers confirm. Exit 2 means Jev was unavailable. In that case, or when `optional.jev` is false, answer each prompt yourself from the same evidence. Answer yes only when you can quote the line that shows it, otherwise no.

A failed check with `on_fail: fix` (the default) keeps the stage in progress with the check's id in the evidence column. Fixing it is the next action inside that stage. A failed check with `on_fail: stop` is a blocker. Record the results as `stages.<stage>.checks` in the state file, one `{id, verdict, p_yes}` per check (`p_yes` blank when you answered without Jev). A result older than the branch's latest commit is stale, like any other marker.

## State file

Stages 1 through 4 leave no reliable trace in git or the scm, so completion is tracked in a state file:

```
~/.claude/dotnet-workflow-kit/pipeline/<slug>.json
```

Write it with the `mcp__dotnet-workflow-kit__stage` tool when it is in your tool list. `stage` with `fields` merges into `stages.<stage>` and fills `at` when `done` is true; `current` sets what the bar shows; `item` sets `ticket`, `title`, `shortTitle` and `order` when the item starts. The tool finds or creates the file as below, writes `branch`, `repo` and `worktree`, drops `adopted`, and redraws the progress bar at once. Without the tool (an organisation that blocks mods, or an older kit), edit the file by hand as below.

Key by the ticket id when the branch carries one, else the sanitized branch name. A file that already names the current branch in `branch` is this item's file whatever its name: the progress bar writes one, marked `adopted: true` with only `stages.start` done, for any branch no skill has touched, so every session shows in the Sessions pane. Update that file in place and remove `adopted` on the first write, rather than starting a second file. Shape:

```json
{
  "ticket": "PROJ-1234",
  "title": "Add the thing to the other thing",
  "shortTitle": "Add thing",
  "branch": "feat/PROJ-1234-add-thing",
  "order": [{"id": "start", "label": "Start"}, {"id": "plan", "label": "Plan"}, "..."],
  "current": { "stage": "implement", "detail": "Writing the GetTodo slice", "blocked": false },
  "stages": {
    "start": { "done": true, "at": "2026-09-01T10:00:00Z" },
    "plan": { "done": true, "at": "2026-09-01T12:30:00Z", "artifactUrl": "", "designUrl": "" },
    "implement": { "done": true, "at": "2026-09-01T16:00:00Z", "commits": 4 },
    "sweep": { "at": "2026-09-01T16:20:00Z", "commit": "<sha>", "findings": [], "skipped": [] },
    "test": { "done": false, "at": "", "note": "" },
    "review": { "done": false, "artifactUrl": "", "decision": "" },
    "pullRequest": { "done": false, "url": "" }
  }
}
```

Update it right after completing a stage, including one that happened naturally in conversation without this skill being invoked. `shortTitle` is at most four words. `current` is what the progress bar above the prompt shows between turns: set `stage` and a one-clause `detail` when a stage starts and at each step inside it, and `blocked: true` when the run stops on a blocker, cleared when it resumes. Live signals always win: if the file says no PR exists but the scm adapter finds one, trust the scm and backfill the file. Manual overrides: "/next done <stage>" marks a stage complete, "/next reset" clears the file.

**Files written by 0.5.0** use older keys. Map them once on first read, then rewrite the file: `startTicket` to `start`; `execute` plus `megaReview` to `implement` (done when both were) and `sweep` (from `megaReview.findings`, with `commit` left blank so the sweep counts as stale); `qa` to `test`; `draftPr` and `resolveComments` fold into `pullRequest` with `handoff.done` as its `done`.

## The status table

```
PROJ-1234 - Add thing (feat/PROJ-1234-add-thing)

| # | Stage | Status | Evidence |
|---|-------|--------|----------|
| 0 | Start | done | branch + active |
| 1 | Plan | done | plan approved 1 Sep |
| 2 | Implement | done | 4 commits ahead of base, sweep clean, checks 2/2 |
| 3 | Test | in progress | 5/6 scenarios pass |
| 4 | Review | todo | |
| 5 | Pull request | todo | #42 draft, checks green |

Next: fix the failing scenario and rerun test.
```

Statuses are plain words: done, in progress, todo, blocked. Keep evidence to a count, a date, a PR number or one clause. The "Next" line names the earliest stage that is not done; unless this is "/next status", it starts right after the table prints.

## Running without input

Invoking the pipeline is standing approval for everything up to the checkpoint, including commits, pushing the branch, opening the draft PR, and applying `qa.deploy_label`. A draft PR is a safe intermediate: nothing is announced to anyone. Whichever stage opens the PR, in Claude desktop it is then opened in the Claude browser, as the scm adapter says, unless `pipeline.open_pr_in_browser` is `false`. It also switches on CI auto-fix for the PR, as the adapter says, unless `pipeline.auto_fix_pr` is `false`. Never pause for a per-stage confirmation; announce each stage with a one-liner and report a one-line delta between stages, not the full table.

Sweep findings get fixed, not queued for permission, unless a fix would change the ticket's scope. Test failures likewise: fix and re-run until green.

Stop only for a big blocker, something the user genuinely has to decide or that cannot be self-served:

- Failing CI that is not this branch's fault: the failing job touches files outside the diff, or the same job is red on the base branch too. Retry once silently; if it stays red against unrelated infrastructure, that is the blocker. With `optional.jev`, classify each red job first: its name plus the last 60 log lines, `context` the diff's file list, classes `this_branch` (fix it inside the stage), `unrelated_infrastructure` and `flaky` (retry once, then the blocker), `manual_review` (read the log yourself).
- A merge conflict with the base branch that is not mechanically resolvable.
- A missing or default-sourced profile: suggest `/dotnet-workflow-kit:setup` rather than guessing labels or an environment.
- A stacked parent not yet merged when stage 5 is reached.
- A Test failure whose fix changes scope or touches infrastructure, or a sweep finding that contradicts the ticket's acceptance criteria.
- Missing credentials or access.

When blocked, set `current.blocked` to true with the blocker as `current.detail`, print the table, state the blocker and a recommended resolution in two or three sentences, end with the gate line (see Stopping at a gate), and stop.

## The checkpoint

When stages 0 through 3 are done and the review page is built, present everything in one message and stop. Its first line is, word for word, "/next has reached the review checkpoint for <item>." Then:

1. The draft PR link when one exists and a one-paragraph summary of the change.
2. The review artifact link, its Verdict line, and the headline numbers as a small table (acceptance, manual QA, open findings, criteria covered). Do not paste the QA report body.
3. The final status table.
4. The gate line.

The review link goes in the checkpoint message itself as a plain URL; a link only inside a subagent's transcript does not count as delivered.

Then wait. When the user says "decided", a "Review decision" artifact comment arrives from the page, or the user invokes the pipeline again, read the decision with the Artifact tool: `read_db`, `db_op: "list"`, `collection: "review"`, url from `review.artifactUrl`. The `decision` document carries `verdict` (`approve` or `changes`) and `notes`; `finding-<n>` documents carry `action` (`fix` or `accept`) per open finding. Approve continues to stage 5 in the same turn, with no further confirmation. Changes returns to stage 2 with the notes and the per-finding fix or accept choices, then rebuilds and republishes the review to the same URL before re-presenting only what changed. With `artifacts: false`, take the verdict in chat instead.

## Stopping at a gate

Every stop, whether the plan gate, the checkpoint or a blocker, ends its message with this line, word for word:

> Gate reached: /next has stopped and needs your reply. It will not continue until you answer.

A stop is a finished run, not pending work, so `/goal` conditions such as "/next has stopped at a gate" read it as met. A turn that arrives with no new user message, such as a `/goal` or Stop-hook re-prompt, is not a decision: do not re-read the page, do not poll, and do not rephrase the wait. Repeat the gate line once and end the turn. Only "answered", "decided", a "Plan decision" or "Review decision" artifact comment from the page, or a user-typed invocation re-reads a stored decision. An approve read this way resumes the run at once.

## Goals

The kit's hooks set the run's goals; this skill never runs `/goal` itself. When the plan is recorded as approved, they set `/goal /next has reached the review checkpoint`, met by the checkpoint's first line. When the review decision is recorded as `approve`, they set `/goal complete /next: the pull request is ready`, met by the final message's first line. Keep both lines word for word, and record the plan approval and the review decision in the state file as soon as they happen, since that is what the hooks watch. A bug-fix run writes `stages.plan` as done when the fix skill writes its plan, and an auto-approved review records its decision the same way, so the same two goals apply. While `current.blocked` is true the hooks keep the goal quiet, so a blocker does not re-prompt.

## The pull request (stage 5)

Push the branch, then let the scm adapter's steps create the draft if Test did not already: title from the ticket, body from the plan's Requirement and Specs, base set to `base_branch` or the stacked parent. The body covers this ticket only and never names another pull request, a stacked parent included; the base is metadata, not prose. Resolve review threads and get checks green. With `optional.jev`, triage the threads before answering any. `jev_screen` each thread's first comment with purpose "decide whether this review comment needs a code change"; a `block` is quoted to the user and left unanswered. Then one `jev_classify` call over the survivors into `needs_code_change`, `question`, `nit`, `already_addressed` and `manual_review`. Then `jev_rerank` the code-change ones against "changes behaviour or a contract". Reply to questions and nits, point already-addressed threads at the commit, and commit for code changes in rank order; read `manual_review` and `review`-decision items yourself. Without Jev, read every thread in order. A thread fix that commits makes Test and Review stale, so they rerun before the PR is marked ready. Once the checkpoint is approved: post the QA report per `qa.evidence`, mark the PR ready, apply `qa.handoff_label` when `qa.owner` is `qa-team`, and move the item to `tracker_states.qa_ready`. `qa.owner` self or none just marks it ready. Merging is the user's action, never the pipeline's. The final message's first line is, word for word, "complete /next: the pull request is ready for <item>.", followed by the PR link and the final status table.

## House rules

- Never enter Claude's plan mode for this pipeline; the plan stage is a published page, not a mode.
- Never remove `qa.handoff_label`, and never change the work item's state from a QA comment; only the tracker adapter's own steps do that.
- Commit only when the current stage requires it, saying so if a commit happens outside stage 2.
- Commit messages never contain a work item id or another PR or commit reference; only the PR title links the tracker. Merge the base in with an explicit `-m` message.
- Use the profile's own label and environment names throughout, never a hardcoded literal.
- Print the plan and review artifact links in the main reply, not only inside a subagent's transcript.
- Investigate and re-run CI failures silently; report findings in chat, not as PR status comments.
- New commits during stage 5 fix feedback only, force-push-with-lease reserved for a rewritten stacked layer.
- A Jev call that cannot run is skipped and said so in one line; the state file records nothing for it, and the pipeline never blocks on Jev being absent.
- A branch conflicting with the base pre-empts whatever stage was next.

## Traps

- A sweep, test or review marker older than the branch's latest commit is stale, not done; downgrade it and redo the stage rather than trust a marker describing an earlier diff.
- Stacked layers: a stage measures only the work above its own parent, never above the ultimate base, and merging a layer merges everything below it, so the checkpoint must name the parent PRs that need to clear QA first. That belongs in the chat checkpoint alone; it never goes into the PR body or the tracker, where the host's own stack view is the source of truth.
- With `artifacts: false`, the pages still render but cannot send a decision back to this session; take every decision in chat and still record it in the state file.
- The pages wake this session only through Send to Claude, which needs the `comments` capability and a session watching the page. Otherwise "answered" or "decided" from the user, or a fresh invocation, triggers a re-read of a stored decision.
