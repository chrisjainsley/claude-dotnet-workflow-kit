# Adapters

An adapter is a markdown file that tells a skill how to do something in terms of the
tool the team actually uses. Skills never branch on a profile value themselves; they
resolve the profile, then read the adapter file the value points to and follow it.
This keeps `plan` and `review` identical across a GitHub team on
Azure Boards and a team that lives entirely in GitHub Issues.

## The pattern

Every adapter lives at:

```
adapters/<concern>/<value>.md
```

`<concern>` is one of five profile keys: `tracker`, `scm`, `architecture`, `qa`, or
`stack`. `<value>` is the enum value the profile holds for that key, so a profile with
`"tracker": "azure-boards"` makes a skill read `adapters/tracker/azure-boards.md`, and
switching the profile to `"tracker": "github-issues"` switches every skill that reads
the tracker adapter to `adapters/tracker/github-issues.md` with no other change.

An adapter is a file by default, but it can be a folder instead when it needs more
than one supporting file (a script, for example): `adapters/<concern>/<value>/README.md`
stands in for `adapters/<concern>/<value>.md`. A skill resolving an adapter tries the
file form first, then falls back to the folder's `README.md` when the adapter is a
folder. `tracker: azure-boards` is the one adapter shipped as a folder today, because
it carries `fetch_context.py` alongside its `README.md`.

`stack` is one level deeper than the other four, because the profile itself nests it:
`stack.data`, `stack.api`, `stack.messaging`, `stack.errors`, `stack.local_run` and
`stack.frontend` each pick their own value independently. Instead of one file per value, each stack field
gets a single file with one `## <value>` section per value it supports:
`adapters/stack/<field>.md`. So `"stack.data": "ef-core"` reads the `## ef-core`
section of `adapters/stack/data.md`, and a ticket that touches both data access and
messaging reads the matching section of `adapters/stack/data.md` and the matching
section of `adapters/stack/messaging.md`, one file per stack field the ticket
actually touches.

## The five concerns

### tracker

Values: `azure-boards`, `github-issues`, `jira`, `none`.

Read by both document skills to fetch a ticket, and by `review` to post the
QA report on approve. Each file has these headings:

- **Fetch a ticket** - the command or API call that returns a ticket's title,
  acceptance criteria and, for a bug, its repro steps.
- **Start work** - how `start` assigns the ticket and moves it to an active
  state.
- **Context for the plan** - how to pull a parent feature, sibling stories and design
  links for the plan's collapsed Context section.
- **Post the QA report** - where the QA report section goes on approve, and any
  formatting the tracker needs (plain text only, how dashes and code fences render,
  what must never appear in a comment the tracker would auto-link).

`tracker: none` skips this adapter entirely; the user's own description stands in for
the ticket, and `qa.evidence` cannot be `work-item` when `tracker` is `none`.

`azure-boards` ships as a folder, `adapters/tracker/azure-boards/`, with the four
headings above in its `README.md` plus `fetch_context.py`, the script `plan`
runs for the plan's Context section. The other tracker values are plain files.

### scm

Values: `github`, `azure-repos`.

Read by `review` to find the PR and by `start` to open one. Headings:

- **Find the PR and base** - the command that returns the PR's base branch, checks and
  merge state, including the stacked-PR case where the real base is not the default
  branch.
- **Draft PR and labels** - how a PR is opened as a draft and which labels move it
  through review and into QA.
- **Review threads** - how to read and reply to review comments and mark a thread
  resolved.
- **Diff range for the review builder** - the exact git invocation the review builder
  passes to compare the branch against its base, and the merged-PR variant that diffs
  a single squash commit instead.

### architecture

Values: `clean`, `vertical`, `ddd-clean`, `modular-monolith`.

Read by both document skills for section and slice naming. Headings:

- **Plan sections** - the section list and word caps `plan` uses beyond
  the shared Context, Requirement, Specs, Tests, Decisions, Risks and rollout, and
  Open questions; for `clean` these are Domain, Application, Infrastructure, API, for
  `vertical` they are Slice, Persistence, Integration, Endpoint.
- **Review slices** - the same layer names as they appear as Slice values in the
  review's per-service Changes tables.
- **What the reviewer looks for** - the architectural rules the reviewer sweep and the
  review's Findings section check for in this architecture (dependency direction,
  where domain logic is allowed to live, what counts as a layering violation).

`ddd-clean` and `modular-monolith` reuse `clean`'s plan sections and review slices
(`scripts/kit_profile.py` aliases both onto the `clean` lists) but keep their own file so
"what the reviewer looks for" can describe their extra rules, such as aggregate
boundaries or module isolation, without overloading the `clean` file.

### qa

Values: `qa-team`, `self`, `none`.

Read by `review` to write the QA report and route the hand-off. Headings:

- **Who signs off** - who is expected to run QA and who has authority to approve.
- **What the QA report must contain** - the scenario format, evidence expectations,
  and what counts as a valid environment and test user for this qa.owner.
- **Hand-off** - what happens after approve: who is notified, and how that ties back
  to `qa.handoff_label` and `qa.deploy_label`.
- **When no QA was run** - the wording the QA report opens with, and what happens to
  the decision form's options when there is no evidence at all.

### stack

Values per field: `stack.data` (`ef-core`, `dapper`, `cosmos`, `other`), `stack.api`
(`minimal-api`, `controllers`, `graphql`, `grpc`), `stack.messaging` (`masstransit`,
`wolverine`, `service-bus`, `none`), `stack.errors` (`result`, `exceptions`),
`stack.local_run` (`aspire`, `docker`, `plain`), `stack.frontend` (`none`, `blazor`,
`razor`, `react`, `angular`, `vue`, `javascript`).

Read by both document skills for whichever fields a ticket's diff actually touches.
`data`, `api`, `messaging`, `errors` and `frontend` files share one heading set, because
each of those describes a piece of the system's shape:

- **Plan: what to name** - the concrete types, project conventions and naming the plan
  should use for this choice, so the plan's Domain, Application, Infrastructure or API
  sections read like the team's own code rather than generic prose.
- **Review: contracts and coordination** - what this stack choice puts in the review's
  Contracts and coordination table (schema changes, event topics, migrations,
  configuration keys) and who else has to move for it.
- **Common findings** - the mistakes the reviewer sweep and the review's Findings section
  should flag for this choice (an N+1 query for `ef-core`, a missing idempotency key
  for `masstransit`, an unhandled `Result` for `result`-style errors).

`frontend` also decides whether `plan` runs its design step at all: `none` means the
plan never carries a Designs section, and any other value names where the look of a
kit-drawn artboard comes from when no design system is attached.

`local_run` is the exception, because it is not about naming or contracts, it is about
getting the system running to gather QA evidence, so its files use a different
heading set:

- **QA stage** - how to start the system locally for this run style (an Aspire
  AppHost, a `docker compose` stack, a plain `dotnet run`), and what the QA report's
  environment line should say when QA ran locally rather than against a shared
  environment.
- **Common issues** - the failure modes specific to this run style that QA and
  reviewers should not mistake for a regression (a stale container, a port already in
  use, a missing local secret).

## Jev is not an adapter

Jev touchpoints live in the skills and the sweep, described once in `docs/jev.md`, and
switch on `optional.jev` rather than on an adapter value. An adapter says how to talk to
a tool the team chose; Jev is a judge the skills consult on any tool's output, so it
never gets a file here.

## Adding a new value

1. Add the new value to the matching entry in `ENUMS` in `scripts/kit_profile.py`, and to
   `PLAN_SECTIONS` or `REVIEW_SLICES` too if it is a new `architecture`.
2. Write `adapters/<concern>/<value>.md` (a new `## <value>` section in
   `adapters/stack/<field>.md` for a stack value) with
   every heading its concern requires, listed above.
3. If dotnet-claude-kit has a skill that matches the new value, add a `NEEDS` entry in
   `scripts/kit_profile.py` so setup recommends it; add a `NEEDS_MCP` entry too if that
   skill depends on an MCP server the kit does not ship itself.
4. Add a fixture under `tests/` that resolves a profile carrying the new value and
   asserts the right adapter file loads, so a later refactor cannot silently drop it.
