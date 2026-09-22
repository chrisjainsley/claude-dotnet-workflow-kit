# dotnet-workflow-kit

A Claude Code plugin for .NET teams that takes work from a ticket through planning,
implementation, review and QA hand-off. It builds plan and review pages with enforced
word budgets, so you can read the proposed work and the results before approving each.

One project profile sets your architecture, tests, tracker and QA workflow. Use the
six skills, start, plan, implement, test, review and next, together or on their own,
with or without a ticket tracker or the Artifact tool.

[Install](#install) | [Workflow](#workflow) | [Skills](#skills) | [/goal](#running-with-goal) | [Branding](#branding) | [Profile reference](#profile-reference) | [dotnet-claude-kit](#dotnet-claude-kit) | [Jev](#jev) | [Contributing](#contributing)

## Install

Run in a terminal:

```bash
claude plugin marketplace add chrisjainsley/claude-dotnet-workflow-kit
claude plugin install dotnet-workflow-kit@dotnet-workflow-kit
```

Then run setup in Claude Code from your project:

```text
/dotnet-workflow-kit:setup
```

Setup asks about your team and writes `.claude/dotnet-workflow-kit.json`. Commit that
file to share the settings. Run setup again when your workflow changes.

The scripts require Python 3.11 or later. Pillow is optional; without it, the plan
builder embeds full-size images instead of downscaling them.

For terminal setup from a clone of this repository:

```bash
python scripts/setup.py
```

## Workflow

Start with a ticket ID, or a short slug when `tracker` is `none`:

```text
/dotnet-workflow-kit:start 1234
```

Use the pipeline driver to continue, or wrap it in a goal so it keeps going until
the next gate:

```text
/dotnet-workflow-kit:next
/goal complete /next
```

The driver checks the branch, PR and saved state, then runs the earliest unfinished
stage. It pauses for plan answers or approval, the review decision, and blockers.
Invoking it authorizes commits, pushes, a draft PR and configured deployment labels
before the review checkpoint. The kit never merges; a person approves every merge.

| Stage | Who | Result |
|---|---|---|
| 0. Start | Agent | Create and push a branch; assign and activate the item when a tracker is configured. |
| 1. Plan | Agent, then you | Build the plan page; you answer the open questions or approve. |
| 2. Implement | Agent | Implement the plan one layer per commit, then run the reviewer sweep, fix findings and verify. |
| 3. Test | Agent | Run the suites, then the plan's scenarios in the configured environment; fix failures and rerun. |
| 4. Review | Agent, then you | Present the final diff, findings and QA evidence on one page; you approve or send it back. |
| 5. Pull request | Agent, then you | Resolve threads and get checks green. After approval, post the QA report, apply labels and mark the PR ready. You merge. |

Requesting changes returns the pipeline to implementation with your notes and
per-finding fix or accept choices. The draft stays a draft until approval.

## Skills

### start

Use to start work from an ID, issue URL or untracked slug. It creates and pushes a
branch from `base_branch` using `branch_pattern`. With a tracker, it assigns the item
to `user` and moves it to the configured active state. It then renames the session
when supported and hands off to plan.

### plan

Use for an implementation plan. It reads the ticket and codebase, then writes
`plans/<id>-<slug>/plan.md` and builds `plan.html`. Sections follow your architecture,
with test scenarios, decisions, risks and open questions. A script checks section
budgets before publication.

When `stack.frontend` is set and a ticket changes a screen that came with no design,
the skill draws the screens first, with Claude Code's `/design` command or the Design
canvas Artifact type, and embeds the artboards in a Designs section of the plan page
next to a link to the editable canvas. Designs supplied by the tracker are used as they
are and no canvas is made.

On an Artifact page, choose answers and press **Send answers**, then tell the session
"answered". The skill reads the stored choices, updates the plan and republishes it.

![Plan page showing Context, Specs and the Open questions form](docs/images/plan-page.png)

### implement

Use to build an approved plan. It walks the plan's layers in order, one commit each,
tests first when `testing.tdd` is strict, then runs the reviewer sweep: read-only
reviewers in parallel, cleanup and verification in sequence. The built-in reviewers
are `bug-hunt` and `conventions`; the profile can enable companion reviewers and a
Codex second opinion. Findings are fixed on the branch before anything is tested, and
missing tools appear in the skipped list with a reason. This skill edits files.

### test

Use to run the Test stage and write up what was tested. It runs the build and the
suites, then the approved plan's scenarios in `qa.environment`, opening the draft PR
and applying `qa.deploy_label` when that environment needs a deployment. It then writes
the QA report, or testing notes for a QA team.

| Mode | Content | Posting |
|---|---|---|
| Report | Given/When/Then scenarios, Pass/Fail/Blocked results, evidence, summary and untested criteria. | After approval, post according to `qa.evidence`. |
| Notes | What changed, steps per persona, test data, edge cases, scope, environment and flags. | After approval, post for `qa-team` according to `qa.evidence`; otherwise print in chat. |

Reports cover acceptance runs against a real environment and manual checks. Unit and
integration suites do not count as QA evidence. Notes come from the approved plan's
Specs, or the diff when no plan exists. Select notes mode with:

```text
/dotnet-workflow-kit:test notes
```

### review

Use to review a branch or PR. It combines the approved plan, actual diff, sweep
findings and QA evidence into `review.md` and `review.html`. When no sweep is fresh
for the branch, it runs one first, so a branch nobody implemented in this session can
still be reviewed.

The page includes verdict counts, plan versus delivered, a change diagram (click it
to open full size), file links
to full diffs, findings, the QA report and a rollout checklist. Choose **Approve** or
**Request changes**, press **Send decision**, then tell the session "decided".
The skill reads the decision and each open finding's fix or accept choice.

![Review page showing verdict tiles, the change diagram and decision form](docs/images/review-page.png)

### next

Use to run the [workflow](#workflow) from the current stage. It reads live signals
alongside `~/.claude/dotnet-workflow-kit/pipeline/<slug>.json` and updates stage completion.
Live evidence overrides saved state; sweeps, test runs and reviews older than new
commits must run again. State files written by 0.5.0 are migrated on first read.

To inspect progress without running a stage:

```text
/next status
```

## Renamed in 0.6.0

The skills now carry the names of the stages they run. Old names are not aliased;
update any saved prompts or `/goal` text.

| Before | Now |
|---|---|
| `start-ticket` | `start` |
| `visual-plan` | `plan` |
| Execute stage inside `next`, plus `mega-review` | `implement` (the sweep lives at `skills/review/sweep.md`) |
| `qa-report`, plus the QA stage inside `next` | `test` |
| `visual-review` | `review` |
| Draft PR, Resolve comments and Publish and hand off stages | `next` stage 5, Pull request |

## Running with /goal

`/next` runs stage after stage inside one turn, but nothing restarts it if the turn
ends early. To keep the pipeline moving until it reaches a gate, wrap it in a goal:

```text
/dotnet-workflow-kit:start 1234
/goal complete /next
```

The goal re-invokes `/next` until it stops at the plan gate, the review checkpoint
or a blocker. At the plan page, send your answers and tell the session "answered",
or approve the plan. At the review page, send your decision and tell the session
"decided". Pages cannot wake the session themselves. After each gate, set the same
goal again to continue.

Tool permission prompts may still require input. When the pipeline reports a
blocker, resolve it before continuing.

## Without the Artifact tool

Set `artifacts` to `false` through setup when the Artifact tool is unavailable.
The skills build the same HTML pages and give you local file paths to open.

Local forms cannot save answers or decisions. Reply in chat with question numbers
and choices, or with "approve" or "changes" and your finding decisions.
Rollout checklist ticks do not persist; track rollout outside the kit.
See [Running without the Artifact tool](docs/without-artifacts.md).

## Branding

The plan and review pages use the [Delivery Labs](https://deliverylabs.co/workflow-kit)
colours and carry an attribution footer linking there. Set `branding` to `false` through
setup, or in the profile file, to render the neutral palette with no footer.

## Profile reference

Setup writes `.claude/dotnet-workflow-kit.json` in the project. Profile resolution
uses an explicit path first, then the project file, then the user file at
`~/.claude/dotnet-workflow-kit.json`, then defaults. Missing fields receive defaults.

Each row below names a field, including nested fields in dotted form.
For example, `testing.tdd` lives inside the `testing` object. Empty strings appear as `""`.

| Field | Allowed values | Default | Purpose |
|---|---|---|---|
| `schema` | Integer | `1` | Profile schema version. |
| `user` | Free text | `""` | Assignee and name used in page prose. |
| `architecture` | `clean`, `vertical`, `ddd-clean`, `modular-monolith` | `"clean"` | Plan section order and review rules. |
| `testing.tdd` | `strict`, `encouraged`, `none` | `"encouraged"` | TDD expectation; strict means tests first during execution. |
| `testing.unit` | `xunit`, `nunit`, `mstest` | `"xunit"` | Unit test framework. |
| `testing.integration` | `webapplicationfactory`, `testcontainers`, `none` | `"webapplicationfactory"` | Integration test approach. |
| `testing.acceptance` | `reqnroll`, `specflow`, `none` | `"none"` | Acceptance test runner; none keeps scenarios without a BDD runner. |
| `qa.owner` | `qa-team`, `self`, `none` | `"self"` | Who tests and signs off. |
| `qa.evidence` | `work-item`, `pr-comment`, `none` | `"none"` | Where approved QA reports go. |
| `qa.handoff_label` | Free text | `""` | PR label for QA hand-off. |
| `qa.deploy_label` | Free text | `""` | PR label to deploy to QA. |
| `qa.environment` | Free text | `"local"` | Environment named in QA evidence. |
| `tracker` | `azure-boards`, `github-issues`, `jira`, `none` | `"none"` | Ticket adapter; none uses your description. |
| `tracker_project` | Free text | `""` | Project or organization identifier for tracker calls. |
| `scm` | `github`, `azure-repos` | `"github"` | PR and diff adapter. |
| `base_branch` | Free text | `"main"` | Starting branch and fallback PR base; stacked work uses its parent. |
| `branch_pattern` | Free text containing `{slug}`; supports `{kind}` and `{id}` | `"{kind}/{id}-{slug}"` | Branch naming template. |
| `branch_kinds.feature` | Non-empty text | `"feat"` | Feature value for the kind token. |
| `branch_kinds.bug` | Non-empty text | `"bug"` | Bug value for the kind token. |
| `tracker_states.active` | Free text | `""` | State when work starts; blank uses the adapter default. |
| `tracker_states.qa_ready` | Free text | `""` | QA hand-off state; blank uses the adapter default. |
| `artifacts` | `true`, `false` | `true` | Publish Artifacts, or build local HTML and take answers in chat. |
| `branding` | `true`, `false` | `true` | Delivery Labs colours and an attribution footer on the plan and review pages; false renders the neutral palette with no footer. |
| `stack.data` | `ef-core`, `dapper`, `cosmos`, `other` | `"ef-core"` | Data access conventions. |
| `stack.api` | `minimal-api`, `controllers`, `graphql`, `grpc` | `"minimal-api"` | API contract style. |
| `stack.messaging` | `masstransit`, `wolverine`, `service-bus`, `none` | `"none"` | Messaging conventions. |
| `stack.errors` | `result`, `exceptions` | `"exceptions"` | Error handling conventions. |
| `stack.local_run` | `aspire`, `docker`, `plain` | `"plain"` | How to start the system for local QA. |
| `stack.frontend` | `none`, `blazor`, `razor`, `react`, `angular`, `vue`, `javascript` | `"none"` | Whether the repo has a frontend and which kind; see the plan skill. |
| `reviewers` | `bug-hunt`, `conventions`, `kit`, `security-scan`, `convention-learner`, `code-review-workflow` | `["bug-hunt", "conventions"]` | Reviewer sweep passes; the two built-ins always run. |
| `pipeline.execute` | Free text | `""` | Execution command; blank implements the plan directly. |
| `pipeline.resolve_comments` | Free text | `""` | Comment-resolution command; blank uses the SCM adapter. |
| `pipeline.qa` | Free text | `""` | QA command; blank runs plan Specs manually per the QA adapter. |
| `optional.dotnet-claude-kit` | `true`, `false` | `false` | Companion plugin availability. |
| `optional.codex` | `true`, `false` | `false` | Enable the Codex second-opinion reviewer. |
| `optional.roslyn-mcp` | `true`, `false` | `false` | Roslyn MCP availability for code-review-workflow. |
| `optional.jev` | `true`, `false` | `false` | Jev availability: a `TYPESAFE_API_KEY` or a `jev` MCP server. Detected by setup. See [Jev](#jev). |
| `jev.flag_at` | Number from 0 to 1 | `0.75` | Probability at or above which a scored check becomes a finding at the rule's severity. |
| `jev.review_at` | Number from 0 to 1, at most `flag_at` | `0.4` | Probability at or above which a scored check is listed as low with "confirm by reading". |
| `checks` | List of `{id, rule, severity, files}` | `[]` | Review checks the conventions reviewer enforces; `files` is an optional glob. Edited in the file, validated by `scripts/doctor.py`. |

Validation requires a tracker when `qa.evidence` is `work-item`. Both `bug-hunt` and
`conventions` remain in the reviewer list.

The `clean`, `ddd-clean` and `modular-monolith` profiles share Domain, Application,
Infrastructure, API and Tests slices. Their adapters define different review rules.
The `vertical` profile uses Slice, Persistence, Integration, Endpoint and Tests.
See [Adapters](docs/adapters.md) for supported tools and extension points.

## dotnet-claude-kit

Setup recommends the companion plugin when your answers need its skills, and asks
before installing it. These mappings come from `scripts/kit_profile.py`:

| Answer | dotnet-claude-kit skills it needs |
|---|---|
| `architecture: clean` | `clean-architecture` |
| `architecture: ddd-clean` | `clean-architecture`, `ddd` |
| `architecture: vertical` | `vertical-slice` |
| `testing.tdd: strict` | `tdd` |
| `stack.data: ef-core` | `ef-core`, `migration-workflow` |
| `stack.api: minimal-api` | `minimal-api`, `openapi`, `api-versioning` |
| `stack.messaging: masstransit` | `messaging` |
| `stack.messaging: wolverine` | `messaging` |
| `stack.errors: result` | `error-handling` |
| `stack.local_run: aspire` | `aspire` |
| `reviewers: kit` | `code-review`, `80-20-review`, `de-sloppify`, `verification-loop` |
| `reviewers: security-scan` | `security-scan` |
| `reviewers: convention-learner` | `convention-learner` |
| `reviewers: code-review-workflow` | `code-review-workflow` (also needs a Roslyn MCP server) |

The workflow kit also runs without the companion. Built-in adapters still guide the
pages; unavailable companion reviewers are recorded as skipped. The
`code-review-workflow` reviewer also requires a Roslyn MCP server.

## Jev

[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is TypeSafe's
System One model: a fast, calibrated judge that returns probabilities, never text. With
`optional.jev` true the kit uses it wherever a skill would otherwise decide on gut feel,
and every call is skipped, never failed, when it is absent. Setup detects a
`TYPESAFE_API_KEY` or a `jev` MCP server. Register the MCP at user scope so it loads in
every project:

```bash
claude mcp add -s user jev -e TYPESAFE_API_KEY=<your key> -- npx -y @jkudish/jev-mcp
```

Add your own review checks to the profile; the conventions reviewer enforces them on
every sweep, and with Jev `scripts/jev_checks.py` scores every added hunk against them
first:

```json
"checks": [
  {"id": "cancellation", "rule": "Every new async method that performs I/O accepts and forwards a CancellationToken", "severity": "high", "files": "**/*.cs"},
  {"id": "clock", "rule": "Use the injected IClock, never DateTime.Now", "severity": "medium", "files": "src/**/*.cs"}
]
```

| Stage | What Jev does |
|---|---|
| start, plan | Screens ticket text and linked items for injected instructions; ranks linked items so only the relevant ones are read. |
| plan | Settles open questions from the research facts, or preselects the recommended option and names the fact that would decide it. |
| implement | Classifies open sweep findings as fixable in scope or scope-changing. |
| sweep | Scores profile checks and the CLAUDE.md rubric per hunk; deduplicates findings; gates the verdict's claims against the diff and test output. |
| test | Buckets failing tests as regression, refactor fallout, flaky or environment before fixing. |
| review | Verifies Plan versus delivered rows, QA Pass evidence and Verdict tiles. |
| next | Classifies red CI jobs; screens, classifies and ranks review threads. |

Diff hunks, claims, test output and ticket text are sent to api.typesafe.ai when a
touchpoint runs; files matching the secret patterns never are. Set `optional.jev` to
`false` when policy forbids it. [docs/jev.md](docs/jev.md) has the call shapes, the
skipped wording and the checks reference.

## Contributing

| Path | Contents |
|---|---|
| `.claude-plugin/` | Plugin and marketplace manifests. |
| `commands/setup.md` | Setup command instructions. |
| `skills/` | Six skills, the reviewer sweep and their supporting files. |
| `adapters/` | Tracker, source control, architecture, QA and stack instructions. |
| `assets/` | Shared page shell. |
| `scripts/` | Profile, setup, checks, rendering and the Jev checks scorer. |
| `docs/` | Usage guides, writing rules, the Jev reference and screenshots. |
| `tests/` | Fixtures and automated checks. |

Run the tests and plugin validation from the repository root before opening a PR:

```bash
python -m pytest
claude plugin validate .
```

Keep examples generic. Hygiene tests check for private identifiers and em dashes.
Follow the [writing rules](docs/writing-rules.md) for plan and review content.

## License

MIT. See [LICENSE](LICENSE).

Author: Chris Ainsley
