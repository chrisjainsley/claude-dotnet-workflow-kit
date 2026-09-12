# dotnet-workflow-kit

dotnet-workflow-kit is a budgeted plan-to-review delivery workflow for .NET teams. A
short implementation plan and a short review are each published as a Claude Artifact
page instead of scrollback or a wiki doc, with a word budget enforced by a script so
nobody has to read five thousand words to approve a ticket. One profile file,
`.claude/dotnet-workflow-kit.json`, tells every skill how the team builds (architecture,
testing, stack), how work flows (tracker, source control, QA) and whether the Artifact
tool is even available, so the same skills produce the right shape of page for a Clean
Architecture GraphQL service or a vertical-slice minimal API without any prompt-writing
per project. It is for .NET teams who want a lightweight, repeatable plan and review
step around Claude Code, whether or not they also run Azure Boards, GitHub Issues, or
nothing at all for tracking.

## Install

```
claude plugin marketplace add chrisjainsley/claude-dotnet-workflow-kit
claude plugin install dotnet-workflow-kit@dotnet-workflow-kit
```

Then run `/dotnet-workflow-kit:setup` inside Claude Code, or `python scripts/setup.py`
in a terminal if you would rather answer questions outside the assistant. Either way
the profile lands at `.claude/dotnet-workflow-kit.json` in the project root. Commit
that file so the whole team shares one workflow instead of each person's local guess.

Python 3.11 or later is required to run the scripts. Pillow is optional; without it,
image downscaling in the plan builder is skipped and full-size images are embedded
instead.

## The workflow

The kit walks one ticket through the same stages every time. Stages are grouped by
which release they ship in: v0.1 has the two document skills and setup, v0.2 adds the
ticket and QA-writing skills, v0.3 adds the reviewer sweep and the pipeline that drives
all of it automatically. Do not try `/next` on v0.1: it does not exist yet, and the
stages below have to be run one at a time by hand.

1. **Start the ticket** (v0.2). `start-ticket` creates a branch from `base_branch`
   using `branch_pattern`, assigns the ticket and moves it to active.
2. **Plan page** (v0.1). `visual-plan-doc` publishes a plan Artifact ordered from the
   requirement outward through the architecture's layers, ending in an open-questions
   form. Answer the open questions directly on the page; each one is a title, context,
   and a set of recommended and alternative options. When you are done, tell the
   session "answered" and it reads the stored choices back and folds them into the plan
   as settled decisions.
3. **Execute.** Implementation proceeds against the approved plan.
4. **Mega-review** (v0.3). Runs the profile's reviewers, always `bug-hunt` and
   `conventions`, plus any optional ones the profile turns on, across the branch
   before a PR goes up.
5. **Draft PR.** Opened against `base_branch` following `branch_pattern`.
6. **QA.** Testing runs the way `qa.owner` and `qa.environment` describe; whatever
   evidence comes out of it feeds the review's QA report section.
7. **Review page** (v0.1). `visual-review-doc` publishes one Artifact that is both the
   code review and the QA report: verdict tiles, a plan-versus-delivered table, a
   diagram of the change, per-service change tables whose files link to their full
   diffs, a findings table, the QA report itself, a persistent rollout checklist, and
   an approve or request-changes decision form.
8. **Hand-off.** On approve, the QA report section is posted wherever `qa.evidence`
   says (a work item, a PR comment, or nowhere at all), and the pipeline (v0.3)
   continues past the checkpoint.

## Skills

### visual-plan-doc

Triggers on "plan this", "visual plan", "plan `<ticket id>`", `/visual-plan-doc`, or
the pipeline reaching the Plan stage. Reads the profile, the ticket through the
tracker adapter, the codebase read-only, and the architecture, stack and testing
adapters for section wording. Produces `plans/<id>-<slug>/plan.md` and `plan.html`,
published as a Claude Artifact (or left as local HTML when `artifacts` is false),
with sections from Context through Open questions and an answerable open-questions
form. **v0.1, shipped.**

### visual-review-doc

Triggers on "review this", "recap", "qa report", "write up the review",
`/visual-review-doc`, or the pipeline reaching the Review stage. Reads the profile,
the PR and diff through the scm adapter, the approved plan and its stored answers,
mega-review findings from the session, and QA evidence gathered by the user or the
session. Produces `review.md` and `review.html`: verdict tiles, plan versus delivered,
a change diagram, per-service change tables linking every file to its diff, findings,
a QA report, a rollout checklist and a decision form. **v0.1, shipped.**

### start-ticket

Triggers on "start ticket" or `/start-ticket <id>`. Reads the profile's `tracker`,
`scm` and `branch_pattern` fields. Produces a branch named from `branch_pattern`, the
ticket assigned and moved to active, and entry into the Plan stage. **v0.2, planned.**

### qa-report

Triggers on "qa report", "write up the testing" or "document what we tested" when
used outside the review-page flow. Reads acceptance runs and manual verification from
the session. Produces a standalone BDD-format QA report added to the work item.
**v0.2, planned.**

### qa-notes

Triggers on "write test notes" or "qa notes". Reads the session's manual test
activity. Produces a lighter QA note on the work item than a full QA report.
**v0.2, planned.**

### mega-review

Triggers on "mega review", "full review", "review everything" or "pre-PR check".
Reads the branch diff, CLAUDE.md conventions, and the profile's reviewer list
(`bug-hunt` and `conventions` always, plus any optional ones turned on). Produces a
consolidated findings list that feeds the review page's Findings section.
**v0.3, planned.**

### next

Triggers on "next", "what's next", "keep going", "run the pipeline", or setting it as
the session goal; `/next status` prints a status table only. Reads the profile and the
branch or work item's current stage. Produces automatic progression through
start-ticket, plan, execute, mega-review, draft PR and QA, stopping only at the review
checkpoint or on a blocker, then posts the QA report and hands off on approval.
**v0.3, planned.**

## Profile reference

All fields live in `.claude/dotnet-workflow-kit.json`. Dotted names below are nested
under their parent object (for example `testing.tdd` is `{"testing": {"tdd": ...}}`).

| Field | Allowed values | Default | What it changes |
|---|---|---|---|
| `user` | free text | `""` (shown as "you") | The name used in plan and review page prose. |
| `architecture` | `clean`, `vertical`, `ddd-clean`, `modular-monolith` | `clean` | The plan's section order and word caps, the review's slice names, and which `adapters/architecture/<value>.md` loads. |
| `testing.tdd` | `strict`, `encouraged`, `none` | `encouraged` | How firmly the plan and review state the TDD expectation. |
| `testing.unit` | `xunit`, `nunit`, `mstest` | `xunit` | The unit test framework named in the Tests section. |
| `testing.integration` | `webapplicationfactory`, `testcontainers`, `none` | `webapplicationfactory` | The integration test style named in Specs and Tests. |
| `testing.acceptance` | `reqnroll`, `specflow`, `none` | `none` | Whether Specs promises a BDD feature file and which runner drives it. |
| `qa.owner` | `qa-team`, `self`, `none` | `self` | Who signs off in the review's QA section; loads `adapters/qa/<value>.md`. |
| `qa.evidence` | `work-item`, `pr-comment`, `none` | `none` | Where the QA report is posted on approve. |
| `qa.handoff_label` | free text | `""` | The PR label that hands a PR to QA, named in Rollout. |
| `qa.deploy_label` | free text | `""` | The PR label that deploys to the QA environment, named in Rollout. |
| `qa.environment` | free text | `"local"` | The environment named throughout the QA report. |
| `tracker` | `azure-boards`, `github-issues`, `jira`, `none` | `none` | How the ticket is fetched; loads `adapters/tracker/<value>.md`. |
| `tracker_project` | free text | `""` | The project or org identifier passed to tracker commands. |
| `scm` | `github`, `azure-repos` | `github` | How the PR, base and diff are found; loads `adapters/scm/<value>.md`. |
| `base_branch` | free text | `"main"` | The branch PRs target and diffs compare against. |
| `branch_pattern` | free text, must contain `{slug}` | `"{kind}/{id}-{slug}"` | The branch naming template `start-ticket` uses. |
| `artifacts` | `true`, `false` | `true` | Whether pages publish as Claude Artifacts or open as local HTML with answers taken in chat. |
| `stack.data` | `ef-core`, `dapper`, `cosmos`, `other` | `ef-core` | The data access named in Infrastructure and Contracts sections. |
| `stack.api` | `minimal-api`, `controllers`, `graphql`, `grpc` | `minimal-api` | The API style named in the API and Contracts sections. |
| `stack.messaging` | `masstransit`, `wolverine`, `service-bus`, `none` | `none` | The messaging technology named in Infrastructure and Contracts. |
| `stack.errors` | `result`, `exceptions` | `exceptions` | The error handling convention named in Application and API sections. |
| `stack.local_run` | `aspire`, `docker`, `plain` | `plain` | How the QA stage describes starting the system locally. |
| `reviewers` | `bug-hunt`, `conventions` (always on), plus `kit`, `security-scan`, `convention-learner`, `code-review-workflow` | `[bug-hunt, conventions]` | Which reviewers mega-review runs beyond the two built-ins. |
| `optional` | object with `dotnet-claude-kit`, `codex`, `roslyn-mcp`, each `true`/`false` | all `false` | Whether the companion kit, Codex and a Roslyn MCP server were detected or installed. |
| `schema` | integer | `1` | Internal profile version; setup fills in defaults for anything an older file lacks. |

Two invariants are enforced on every write and every load:

- `qa.evidence` cannot be `work-item` unless `tracker` is something other than `none`.
- `reviewers` always includes `bug-hunt` and `conventions`; they cannot be removed.

## dotnet-claude-kit

Setup recommends the companion `dotnet-claude-kit` plugin and offers to install it
whenever one of your answers needs a skill it provides. The mapping:

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

The kit runs fine without it. Plan sections still work using only the built-in
adapters; the difference is that the extra `kit`, `security-scan`,
`convention-learner` and `code-review-workflow` reviewers in mega-review are skipped
and reported as such, rather than run.

## Screenshots

![Plan page](docs/images/plan-page.png)
The plan page's Context, Specs and Open questions sections with the answer form open.

![Review page](docs/images/review-page.png)
The review page's verdict tiles, change diagram and decision form.

## Architecture support

`clean`, `ddd-clean` and `modular-monolith` all share the same plan section order and
review slice names (Domain, Application, Infrastructure, API, Tests); the latter two
describe different governance around that same structure. `vertical` is fully defined,
with its own section order (Slice, Persistence, Integration, Endpoint, Tests), but it
is not yet exercised by the test fixtures, so treat it as less proven than `clean`
until fixtures cover it.

## Repository layout

```
claude-dotnet-workflow-kit/
├── .claude-plugin/   # plugin.json and marketplace.json
├── adapters/         # tracker, scm, architecture, qa, stack value files
├── commands/         # setup.md, the /dotnet-workflow-kit:setup command
├── docs/             # this reference documentation
├── scripts/          # profile.py, setup.py
├── skills/           # visual-plan-doc, visual-review-doc (v0.1); more from v0.2
└── tests/            # pytest fixtures and skill tests
```

## Contributing

Run `pytest` before opening a PR; the profile, setup and skill build scripts are all
covered by fixture-backed tests in `tests/`. Run `claude plugin validate .` to check
the plugin manifest and the command and skill front matter. CI also runs a
private-string gate that scans the diff for internal identifiers, such as an
employer's name, an internal hostname, or a personal email address, that must never
land in this public repository; keep any examples you add generic.

## License

MIT. See [LICENSE](LICENSE). Author: Chris Ainsley.
