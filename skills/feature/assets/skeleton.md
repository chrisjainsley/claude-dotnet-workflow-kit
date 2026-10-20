---
kind: feature
title: <short name of the feature, two to five words>
ticket: <the feature's tracker id (epic, feature or parent issue), or its slug with tracker none>
base: <the profile base_branch>
size: standard
date: <YYYY-MM-DD>
---

## Summary
<!-- The first thing a reader sees, written for someone coming back cold after days away. Plain prose, no code. What the feature is and where it came from, the problem it solves for users or operators, what is true when every story has shipped, and anything that makes it urgent or blocks it. Readable without the PRD, the Context or the code. -->

## Context
<!-- Collapsed on the page. Where the PRD came from (tracker link, file path or "described in chat"), the area it touches (services, bounded contexts, key aggregates), existing child items reused as stories, and design links. -->

## Requirement
<!-- What the feature changes for users or operators, in plain product terms, then one concrete example with real-looking data. Not the PRD copied. -->

## Stories
<!-- One table, exactly these four columns. A story is one pull request a reviewer can approve on its own: one behaviour, end to end through the layers it needs. Keys are S1, S2 and so on, up to twelve; more means the feature should be split. Depends on lists the keys whose code this story builds on, comma separated, or "-". Size is small, standard or large and becomes the story plan's size. One short line of prose under the table at most. -->

| Key | Story | Depends on | Size |
|---|---|---|---|
| S1 | <As a ..., I can ... so that ...> | - | standard |
| S2 | <...> | S1 | small |

## Story specs
<!-- One ```gherkin fence per story, opening with "Feature: <key> <title>", holding up to four scenarios. These are the acceptance criteria each story's thread copies into its own plan verbatim, so write them as the contract. No prose beyond one line on how they are driven. -->

```gherkin
Feature: S1 <title>

  Scenario: <behaviour>
    Given ...
    When ...
    Then ...
```

```gherkin
Feature: S2 <title>

  Scenario: <behaviour>
    Given ...
    When ...
    Then ...
```

## Delivery order
<!-- Paste the output of scripts/feature_order.py --markdown: the waves, then what each story branches from and when its thread starts. Add at most two lines on why a dependency exists when the table cannot show it. -->

## Decisions
<!-- Up to six bullets: "Chose X over Y because Z." Cross-story choices only: where a shared type lives, which story owns a migration, what the first story stubs for the later ones. -->

## Risks and rollout
<!-- Up to five bullets: what must land first, what a later story could break in an earlier one, feature flags, and how the stories are released together or one by one. -->

## Open questions
<!-- Up to three numbered items, in the plan's syntax: question title, context, nested options with exactly one [x] recommended. Questions that decide the split or the order belong here; a question inside one story belongs to that story's own plan. Write "None." if every decision is made. -->

1. <Question title?> <One or two sentences of context.>
   - [x] **<Recommended option.>** <Why it is the default.>
   - [ ] **<Alternative.>** <What it costs or buys.>
2. Anything else to preserve or avoid?
