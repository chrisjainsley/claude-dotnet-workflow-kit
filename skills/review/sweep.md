# The reviewer sweep

A single pre-PR sweep that fans out across every reviewer the profile enables, then
consolidates the results into one report. Read-only reviewers run in parallel
sub-agents, mutating cleanup runs sequentially in the main agent afterward so two tools
never fight over the same file, and verification runs last on the cleaned tree.

Two skills run it. `implement` runs it at the end of the Implement stage so findings are
fixed before anything is tested. `review` runs it when the pipeline state holds no sweep
newer than the branch's latest commit, so a branch nobody implemented in this session
can still be reviewed cold. `SKILL_DIR` below means the base directory of the skill
that is running the sweep; the reviewer briefs live at
`<plugin root>/skills/review/reviewers/`, and adapters at `<plugin root>/adapters/`.

## Profile

The profile decides:

- `reviewers`: which Phase 1 reviewers run. The two built-ins, `bug-hunt` and
  `conventions`, are always present. `kit` adds `dotnet-claude-kit:code-review` and
  `dotnet-claude-kit:80-20-review` to Phase 1, `dotnet-claude-kit:de-sloppify` to
  Phase 2, and `dotnet-claude-kit:verification-loop` to Phase 3. `security-scan` adds
  `dotnet-claude-kit:security-scan`. `convention-learner` adds
  `dotnet-claude-kit:convention-learner`. `code-review-workflow` adds
  `dotnet-claude-kit:code-review-workflow`, but only when `optional.roslyn-mcp` is true.
- `optional.codex`: when true, adds a codex second-opinion reviewer.
- `optional.jev`, `jev.flag_at`, `jev.review_at`, `checks`: when `optional.jev` is true,
  `scripts/jev_checks.py` scores every profile check (and the rubric it extracts from
  the CLAUDE.md files) against the diff before Phase 1. `jev_compare` then deduplicates
  the consolidated findings, and `jev_gate` checks the verdict's claims after Phase 3. With
  `optional.jev` false the checks still run inside the conventions reviewer. See
  `docs/jev.md` for the call shapes and the skipped wording.
- `optional.dotnet-claude-kit`: when false, every `kit`-gated reviewer is recorded as
  skipped instead of invoked, even if `kit` is in `reviewers`.
- `architecture`: which adapter the built-in reviewers load for stack-specific
  anti-patterns. Read `adapters/architecture/<value>.md`.
- `scm`: how to resolve the PR and its base. Read `adapters/scm/<value>.md`.
- `base_branch`: the fallback base when no PR exists yet.
- `testing.*`: what Phase 3's manual fallback treats as the test suite.

Any reviewer whose skill or plugin is missing is recorded as `skipped: <reason>` and the
run continues.

## Steps

1. **Resolve the base and confirm there is a diff.** Use the scm adapter:
   ```bash
   base=$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null); base=${base:-<base_branch>}
   git fetch origin "$base" -q
   git diff --stat "origin/$base...HEAD"
   ```
   If the diff is empty, stop and say so. If it is under 30 changed lines total, do not
   fan out; tell the user the diff is too small for the orchestration overhead and run
   a single targeted reviewer instead (`conventions` for a rules check, `bug-hunt` for
   a defect pass).
2. **Confirm the working tree is clean.** `git status --short`. If dirty, list the files
   and ask whether to stash and continue or abort. Do this before spawning any sub-agent
   so Phase 1 time is never wasted on a run the user then aborts.
3. **Tell the user what is about to run**, in one line: the reviewer list from the
   profile, how many profile checks there are and whether Jev scores them, the cleanup
   step, and the verification step.
4. **Score the checks with Jev**, before any sub-agent spawns, when `optional.jev` is
   true and the profile has checks or a CLAUDE.md exists:
   ```bash
   python "<plugin root>/scripts/jev_checks.py" --extract <every CLAUDE.md and AGENTS.md the conventions reviewer would collect> --out ~/.claude/dotnet-workflow-kit/pipeline/<slug>-rules.json
   python "<plugin root>/scripts/jev_checks.py" --range "origin/$base...HEAD" --rules ~/.claude/dotnet-workflow-kit/pipeline/<slug>-rules.json --out ~/.claude/dotnet-workflow-kit/pipeline/<slug>-checks.json
   ```
   Skip the first command when no CLAUDE.md or AGENTS.md exists. Both write next to the
   state file, never into the checkout. Exit 2 means Jev was unavailable: record
   `skipped: jev unavailable: <reason>` and continue with the conventions reviewer
   alone. Record the checks path under `sweep.checks` in the state file.
5. **Phase 1, parallel read-only reviewers.** Spawn one sub-agent per enabled reviewer
   in a single message so they run concurrently. Each is read-only and must not edit
   files. Brief each one:

   > You are a read-only reviewer. Invoke `<reviewer>` on the current branch's diff
   > against `origin/<base>`. Do not edit any files. Return: (1) the top 5 issues ranked
   > by severity, (2) any blockers that should stop a PR, (3) a one-paragraph summary.
   > Keep it under 400 words.

   For `bug-hunt` and `conventions`, the sub-agent's brief is the content of
   `reviewers/bug-hunt.md` and `reviewers/conventions.md` respectively; hand it that
   file's content plus the resolved diff range and the architecture adapter path. The
   conventions brief also gets the profile's `checks` list and, when step 4 ran, the
   path of `<slug>-checks.json`. For a `codex` reviewer, frame the task as a second-opinion review, not a fix, via
   `codex:rescue`; if the Codex CLI is not available, record `skipped: codex CLI
   unavailable` rather than failing the run.
6. **Phase 2, sequential cleanup**, once every Phase 1 sub-agent has returned. Run this
   in the main agent, not a sub-agent, so edits land in the working tree directly:
   - With `kit` enabled and installed: run `dotnet-claude-kit:de-sloppify`.
   - Otherwise, a manual tidy pass: `dotnet format` on the affected solution, remove
     unused `using` directives, delete commented-out and unreachable code the diff
     introduced, and drop any dead private member it added but never calls. Keep it
     mechanical; do not restructure logic here.
   If the user chose to proceed over a dirty tree in step 2, stash their unrelated edits
   first so cleanup only touches the diff under review.
7. **Phase 3, verification**, on the cleaned tree, sequential in the main agent:
   - With `kit` enabled and installed: run `dotnet-claude-kit:verification-loop`.
   - Otherwise: `dotnet build` then `dotnet test` on the solution(s) the diff touches,
     naming what counts as a test from `testing.unit`, `testing.integration` and
     `testing.acceptance`. A build failure stops here; do not run tests against code
     that does not compile.
8. **Consolidate**, as the report section below describes. With `optional.jev`, load
   `jev_compare` and run it on every pair of findings that name the same file within ten
   lines of each other; `same_fact` at decision `auto` merges them into one row noting
   both sources. When merged findings disagree on severity, keep the higher one unless
   the reviewers' reasons differ, in which case read both and decide. Without Jev,
   deduplicate by reading.
9. **Gate the verdict.** With `optional.jev`, load `jev_gate` and call it with the
   ticket's Requirement as `request`, the diff, the raw Phase 3 runner output as
   `tests`, and one claim per fact the report is about to state: the verdict line, each
   finding marked `fixed`, and the verification line. `escalate` means a claim is
   unsupported or contradicted: the verdict cannot be READY FOR PR; write NEEDS WORK
   with the reason codes and say which claim failed. `review` is reported as a note in
   the Jev block. Record `sweep.gate` as `{"action", "reason_codes", "safe_to_apply"}`.
   Without the MCP, write `skipped: jev MCP not loaded` in the Jev block.
10. **Write the pipeline state.** Save the consolidated findings to
   `~/.claude/dotnet-workflow-kit/pipeline/<slug>.json` under the key `sweep`, as
   `{"at": "<ISO time>", "commit": "<HEAD sha>", "findings": [...], "skipped": [...],
   "checks": "<path or empty>", "gate": {...} or omitted}`, one entry per reviewer in
   each finding and skipped list. The `review` skill reads this key and copies it
   into its Findings section instead of re-running a review; a `commit` older than
   HEAD means the sweep is stale and must run again.
11. **Report** the consolidated report described below, in chat.

## Consolidated report

One report, one table, under 600 words total.

```
# Sweep report: <branch>

## Verdict
<READY FOR PR | NEEDS WORK | BLOCKED>
<one sentence why>

## Findings
| Severity | Location | Finding | Source | Status |
|---|---|---|---|---|
| high | path/to/file.cs:42 | ... | bug-hunt | open |
| medium | path/to/file.cs:108 | ... | conventions | fixed |

## Phase 2, cleanup applied
- <de-sloppify | manual tidy>: N files changed, one-line summary

## Phase 3, verification
- <verification-loop | build+test>: pass/fail + key signal

## Skipped
- <reviewer>: <reason>

## Jev
- checks: <n> rules, <n> hunks, <n> requests, <n> findings | skipped: <reason>
- gate: <auto | review | escalate> (<reason codes>) | skipped: <reason>

## Recommended next steps
1. ...
```

Deduplicate: if two reviewers flag the same defect, list it once and note both sources
(`jev_compare` finds the pairs when Jev is available). A `checks:<id>` row carries its
Jev probability in the Finding cell.
Status is `fixed` (Phase 2 addressed it), `accepted` (left as-is, with a reason), or
`open` (unresolved).

## Guardrails

- Do not run on a clean branch; no diff means nothing to review.
- Do not push or open PRs. The sweep only reports and cleans locally.
- Do not loop. If a phase fails twice, stop and surface the failure instead of retrying.
- Before Phase 2, the tree must be clean of unrelated uncommitted edits, so the user's
  mid-flight work never gets bundled into a cleanup commit.
- Phase 1 sub-agents stay under 400 words each; the consolidated report stays skimmable.
- Jev receives diff hunks, claims and test output. `jev_checks.py` never sends files that
  match the secret patterns; do not paste their contents into a gate call either. A team
  whose policy forbids sending code to a third party sets `optional.jev` to false.

## Why this shape

Parallel sub-agents keep a broad sweep fast. Mutating reviewers can conflict with each
other, so cleanup stays sequential where edits are observable. Verification runs last
because the tree it checks should be the one that actually ships.
