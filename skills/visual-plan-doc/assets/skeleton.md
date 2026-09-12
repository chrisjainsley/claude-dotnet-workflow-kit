---
title: <short name, two to five words, no ticket number>
ticket: <tracker id, e.g. AB#1234, #567, PROJ-89>
branch: <per the profile's branch_pattern>
base: <the profile base_branch, or "PR <n> (<branch>), retarget when it merges">
size: standard
date: <YYYY-MM-DD>
---

## Context
<!-- Collapsed on the page. Gather it the way the tracker adapter says (Azure Boards: scripts/fetch_context.py <id> --out plans/<slug>/context) and paste the stub here, then fill in Area. Parent feature with link and one-line purpose; sibling stories with state; Area = services, bounded context, key aggregates or handlers; design links and screenshots as ![caption](context/file.png). -->

## Requirement
<!-- What changes for the user or operator, in plain product terms, then one concrete example with real-looking data. Not the ticket text copied. -->

## Specs
<!-- The Gherkin scenarios that will become the acceptance tests, verbatim, in one ```gherkin fence. Up to six. One line of prose only if the scenarios need a note on how they are driven. -->

```gherkin
Feature: <name>

  Scenario: <behaviour>
    Given ...
    When ...
    Then ...
```

## Domain
<!-- Aggregates, value objects, events, enums that change, as type signatures in a ```csharp fence. Prose only for an invariant the signature cannot show. "No change." if untouched. -->

## Application
<!-- Handlers, use cases, service interfaces. Signatures plus one line each on what the method guarantees. Show the load-bearing branch as code, not as a paragraph about code. -->

## Infrastructure
<!-- One table: Concern | Change. Rows come from the stack adapters: persistence, read models, messaging, configuration keys, infrastructure as code, external services. "None" rows are fine and short. -->

| Concern | Change |
|---|---|
| Persistence | |
| Read models | |
| Messaging | |
| Config | |
| Infrastructure as code | |

## API
<!-- The contract delta in the API style's notation (```graphql SDL, endpoint list, proto), or "No API change." plus how errors surface. -->

## Tests
<!-- One table: Project | Class | Cases. Cases are Given_Then names or short phrases, comma separated. Acceptance row points at the feature file. One line for shared test infra changes. -->

| Project | Class | Cases |
|---|---|---|
| | | |

## Decisions
<!-- Up to six bullets: "Chose X over Y because Z." Rationale only where a reader would otherwise ask why. -->

## Risks and rollout
<!-- Up to five bullets: what can go wrong, what must happen first (infrastructure, config flags, stacked PR base), how it is verified in the QA environment. -->

## Open questions
<!-- Up to three numbered items. First sentence is the question title, the rest is context. Nested options render as radio buttons; exactly one "[x]" marks the recommended default and is preselected. A question with no options becomes a free-text answer. Write "None." if every decision is made. -->

1. <Question title?> <One or two sentences of context the reviewer needs.>
   - [x] **<Recommended option.>** <Why it is the default, one or two sentences.>
   - [ ] **<Alternative.>** <What it costs or buys.>
2. Anything else to preserve or avoid?
