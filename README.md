# dotnet-workflow-kit

A Claude Code plugin for .NET teams that takes work from a ticket through planning,
implementation, review and QA hand-off. It builds plan and review pages with enforced
word budgets, so you can read the proposed work and the results before approving each.

One project profile sets your architecture, tests, tracker and QA workflow. Use the
six skills together or on their own, with or without a ticket tracker or the Artifact tool.

[Install](#install) | [Workflow](#workflow) | [Skills](#skills) | [/goal](#running-with-goal) | [Profile reference](#profile-reference) | [dotnet-claude-kit](#dotnet-claude-kit) | [Contributing](#contributing)

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
/dotnet-workflow-kit:start-ticket 1234
```

Use the pipeline driver to continue:

```text
/dotnet-workflow-kit:next
```

The driver checks the branch, PR and saved state, then runs the earliest unfinished
stage. It pauses for plan answers or approval, the review decision, and blockers.
Invoking it authorizes commits, pushes, a draft PR and configured deployment labels
before the review checkpoint.

| Stage | Result |
|---|---|
| 0. Start ticket | Create and push a branch; assign and activate the item when a tracker is configured. |
| 1. Plan | Build the plan page; read your answers or approval. |
| 2. Execute | Implement the plan, using the configured command when set. |
| 3. Review | Run mega-review, clean up and verify the branch. |
| 4. Draft PR | Open a draft against the base branch or stacked parent; check CI. |
| 5. Resolve comments | Address review threads and check CI again. |
| 6. QA | Run the scenarios in the configured environment; fix failures and rerun. |
| 7. Review page | Present the final diff, findings and QA evidence for your decision. |
| 8. Publish and hand off | After approval, post the QA report where configured and mark the PR ready. Follow the QA adapter for labels and tracker state. |

Requesting changes returns the pipeline to implementation with your notes and
per-finding fix or accept choices. The draft stays a draft until approval.

## Skills

### visual-plan

Use for an implementation plan. It reads the ticket and codebase, then writes
`plans/<id>-<slug>/plan.md` and builds `plan.html`. Sections follow your architecture,
with test scenarios, decisions, risks and open questions. A script checks section
budgets before publication.

On an Artifact page, choose answers and press **Send answers**, then tell the session
"answered". The skill reads the stored choices, updates the plan and republishes it.

![Plan page showing Context, Specs and the Open questions form](docs/images/plan-page.png)

### visual-review

Use to review a branch or PR. It combines the approved plan, actual diff,
mega-review findings and QA evidence into `review.md` and `review.html`.

The page includes verdict counts, plan versus delivered, a change diagram, file links
to full diffs, findings, the QA report and a rollout checklist. Choose **Approve** or
**Request changes**, press **Send decision**, then tell the session "decided".
The skill reads the decision and each open finding's fix or accept choice.

![Review page showing verdict tiles, the change diagram and decision form](docs/images/review-page.png)

### start-ticket

Use to start work from an ID, issue URL or untracked slug. It creates and pushes a
branch from `base_branch` using `branch_pattern`. With a tracker, it assigns the item
to `user` and moves it to the configured active state. It then renames the session
when supported and hands off to visual-plan.

### qa-report

Use for a standalone QA report or testing instructions. If a review page already
contains the QA report, this skill reuses that section.

| Mode | Content | Posting |
|---|---|---|
| Report | Given/When/Then scenarios, Pass/Fail/Blocked results, evidence, summary and untested criteria. | After approval, post according to `qa.evidence`. |
| Notes | What changed, steps per persona, test data, edge cases, scope, environment and flags. | After approval, post for `qa-team` according to `qa.evidence`; otherwise print in chat. |

Reports cover acceptance runs against a real environment and manual checks. Unit and
integration suites do not count as QA evidence. Notes come from the approved plan's
Specs, or the diff when no plan exists. Select notes mode with:

```text
/dotnet-workflow-kit:qa-report notes
```

### mega-review

Use before opening a PR. It runs read-only reviewers in parallel, then applies
cleanup and runs verification in sequence. The built-in reviewers are `bug-hunt` and
`conventions`. The profile can enable companion reviewers and a Codex second opinion.

Missing tools appear in the skipped list with a reason. The result includes
consolidated findings, cleanup changes and verification results. It saves findings
for visual-review to reuse. This skill can edit files during cleanup.

### next

Use to run the [workflow](#workflow) from the current stage. It reads live signals
alongside `~/.claude/dotnet-workflow-kit/pipeline/<slug>.json` and updates stage completion.
Live evidence overrides saved state; reviews and QA results older than new commits
must run again.

To inspect progress without running a stage:

```text
/next status
```

## Running with /goal

If your Claude Code session supports the goal command, use it to keep the pipeline
moving toward a stated checkpoint. Plan approval and the review decision still need
your input.

Start the ticket, then set a bounded goal:

```text
/dotnet-workflow-kit:start-ticket 1234
/goal Run /next until it stops at the review checkpoint for ticket 1234 and has printed the review page link. Stop within 3 hours.
```

At the plan page, send your answers and tell the session "answered", or approve the
plan. At the review page, send your decision and tell the session "decided".
Pages cannot wake the session themselves.

After approving, you can set a goal for hand-off:

```text
/goal Run /next until the hand-off stage reports done for ticket 1234. Stop within 1 hour.
```

Name an observable result and include a time bound. Tool permission prompts may
still require input. When the pipeline reports a blocker, resolve it before continuing.

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
| `reviewers` | `bug-hunt`, `conventions`, `kit`, `security-scan`, `convention-learner`, `code-review-workflow` | `["bug-hunt", "conventions"]` | Review passes; the two built-ins always run. |
| `pipeline.execute` | Free text | `""` | Execution command; blank implements the plan directly. |
| `pipeline.resolve_comments` | Free text | `""` | Comment-resolution command; blank uses the SCM adapter. |
| `pipeline.qa` | Free text | `""` | QA command; blank runs plan Specs manually per the QA adapter. |
| `optional.dotnet-claude-kit` | `true`, `false` | `false` | Companion plugin availability. |
| `optional.codex` | `true`, `false` | `false` | Enable the Codex second-opinion reviewer. |
| `optional.roslyn-mcp` | `true`, `false` | `false` | Roslyn MCP availability for code-review-workflow. |

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

## Contributing

| Path | Contents |
|---|---|
| `.claude-plugin/` | Plugin and marketplace manifests. |
| `commands/setup.md` | Setup command instructions. |
| `skills/` | Six skills and their supporting files. |
| `adapters/` | Tracker, source control, architecture, QA and stack instructions. |
| `assets/` | Shared page shell. |
| `scripts/` | Profile, setup, checks and rendering. |
| `docs/` | Usage guides, writing rules and screenshots. |
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
