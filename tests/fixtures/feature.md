---
kind: feature
title: Expiring loyalty points
ticket: #120
base: main
size: standard
date: 2026-10-15
---

## Summary

A feature from issue #120. Loyalty points never expire today, so the balance owed to members only grows and old points sit on the books forever. When this feature ships, points expire twelve months after they were earned, oldest first, members are warned by email thirty days ahead, and statements show when points will expire. It is split into four stories that ship one pull request each.

## Context

Source: issue #120, "Points expire after twelve months". Area: the Loyalty service, its `PointsLedger` aggregate and the nightly jobs host. No child issues existed, so all four stories are new.

## Requirement

Earned points expire twelve months after the day they were earned, oldest first. A member who earned 500 points on 3 March 2025 and spent 200 sees 300 expire on 3 March 2026, gets a warning email thirty days before, and sees the date on their statement.

## Stories

| Key | Story | Depends on | Size |
|---|---|---|---|
| S1 | As the ledger, I record the earn date on every lot so expiry can be computed | - | standard |
| S2 | As a member, my unspent points expire twelve months after they were earned | S1 | standard |
| S3 | As a member, I can see when my next points expire on my statement | S1 | small |
| S4 | As a member, I get an email thirty days before points expire | S2 | small |

## Story specs

```gherkin
Feature: S1 Earn date on lots

  Scenario: A new award records its earn date
    Given a member with no points
    When they earn 500 points on 2025-03-03
    Then the ledger holds one lot of 500 earned on 2025-03-03
```

```gherkin
Feature: S2 Expire unspent points

  Scenario: Unspent points expire after twelve months
    Given a lot of 500 points earned on 2025-03-03 with 200 spent
    When the expiry job runs on 2026-03-03
    Then 300 points expire and the balance is 0
```

```gherkin
Feature: S3 Expiry on the statement

  Scenario: The statement shows the next expiry
    Given a lot of 300 unspent points earned on 2025-03-03
    When the member opens their statement
    Then it shows 300 points expiring on 2026-03-03
```

```gherkin
Feature: S4 Expiry warning email

  Scenario: A warning goes out thirty days ahead
    Given a lot of 300 unspent points expiring on 2026-03-03
    When the warning job runs on 2026-02-01
    Then the member is sent one expiry warning email
```

## Delivery order

1. Wave 1: S1.
2. Wave 2: S2, S3.
3. Wave 3: S4.

| Story | Branches from | Starts |
|---|---|---|
| S1 | `main` | now |
| S2 | the branch of S1, stacked (PR base set by hand) | once S1's review is approved and its pull request is ready |
| S3 | the branch of S1, stacked (PR base set by hand) | once S1's review is approved and its pull request is ready |
| S4 | the branch of S2, stacked (PR base set by hand) | once S2's review is approved and its pull request is ready |

Stacking: `base`.

## Decisions

- Chose lots with an earn date over a running balance because expiry is per earn date.
- Chose S1 to own the migration because every later story reads the column.

## Risks and rollout

- Existing lots have no earn date; S1 backfills it from the award event's timestamp.
- S2 ships behind a flag so expiry can be dry-run in QA before it removes points.

## Open questions

1. What happens to points earned before the feature ships?
   - [x] **They expire twelve months after launch.** Members get a full year's notice.
   - [ ] **They expire on their real earn date.** Some would expire on launch day.
