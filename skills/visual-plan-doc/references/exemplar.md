# Exemplar: AB#17444 re-cut to budget

The original visual-plan output for this ticket ran 3,373 prose words with a flow
diagram, a data model, three annotated code tabs and a question form. This is the
same plan at about 800 prose words. Nothing an implementer would act on differently was
lost. Use it as the bar for density, section shape and tone; do not copy its content.

```markdown
---
title: Signup grant once per payer
ticket: AB#17444
branch: feat/AB#17444/signup-grant-once-per-payer
base: PR 3081 (feat/AB#17431/issue-granted-credit-expiry-date), retarget to dev when it merges
size: standard
date: 2026-09-11
---

## Context
**Parent feature:** [AB#17440 Loyalty Points: Airdrops and Offer Integrity](https://dev.azure.com/example-org/Example%20Project/_workitems/edit/17440) (Feature, New). Eighth chunk under the Free Tier Integrity epic AB#17391; builds on AB#17431, which issues granted credit, and follows the onboarding quests feature AB#17435.

**Siblings in the feature:** [AB#17441](https://dev.azure.com/example-org/Example%20Project/_workitems/edit/17441) campaign admin without a release (Active); [AB#17442](https://dev.azure.com/example-org/Example%20Project/_workitems/edit/17442) spend granted credit first and expire it (Active); [AB#17445](https://dev.azure.com/example-org/Example%20Project/_workitems/edit/17445) refuse the signup grant at checkout to a repeat payer (New).

**Area:** SubscriptionService, Loyalty Points bounded context. `LoyaltyPointsAccountGrain` and its ledger in `Acme.Data.ReadModels.Subscription`, the `SignupCampaignGrantIssuer` on the API wallet read, and the B2C `EnrichToken` connector in UserService for identity at signup.

**Designs:** none. Backend-only story; the member sees no new UI.

## Requirement
A new Free account created under the `signup-grant` campaign gets 1,000 Loyalty Points that expire after 30 days. Today the credit is per account, so a second account is another $10. This story makes it once per payer, where the payer is the email root: lowercased, plus-suffix removed, dots kept. A repeat payer signs up, gets the quests, earns normally, and never sees the credit. Nothing tells them.

Example: `Sam.Jones@gmail.com` took the grant in March. `sam.jones+alias@gmail.com` in September gets nothing. `sam.jones2@gmail.com` gets 1,000. So does `samjones@gmail.com`; Gmail dot variants are AB#17445's job at checkout.

## Specs
Acceptance users carry no signup claim, so the scenarios drive the admin mutation, which follows the same rule.

```gherkin
Feature: Granted Loyalty Points credit

  Scenario: The signup grant reaches a payer once, not once per account
    Given a newly created member holding the signup grant
    And a second member created with a plus alias of that member's email address
    When an admin issues the "signup-grant" campaign credit to the second member
    Then the grant is refused because the payer has already had it
    And the second member's wallet balance is 0

  Scenario: A different person at the same provider still receives the signup grant
    Given a newly created member holding the signup grant
    And a second member created with a different email root at the same provider
    When an admin issues the "signup-grant" campaign credit to the second member
    Then the second member's wallet shows 1000 points of granted credit

  Scenario: A campaign without the once per payer limit credits a repeat payer
    Given a newly created member holding the signup grant
    And a second member created with a plus alias of that member's email address
    When an admin issues the "promo-grant" campaign credit to the second member
    Then the second member's wallet shows 500 points of granted credit
```

## Domain
`PayerKey` hashes the root so no plain email lands in a grain id or state. `GrantCreditResult` gains an outcome enum because today a deferred grant would be indistinguishable from an already-applied one.

```csharp
// Acme.Domain.Subscription/LoyaltyPoints/GrantedCredit/PayerKey.cs
public static class PayerKey
{
    // trim, lowercase, drop local part after '+', keep dots, null without '@'
    // returns "email:" + SHA-256 hex of "local@domain"
    public static string? FromEmail(string? email);
}

public enum GrantCreditOutcome { Granted, AlreadyApplied, Refused, Deferred }
public record GrantCampaignCreditRequest(string CampaignId, int Amount, DateTime ExpiresAtUtc,
    bool ForfeitIfUnusedAtFirstPurchase, bool OncePerPayer, string? PayerKeyFromCaller);
```

## Application
- `IGrantedCreditPayerGrain : IGrainWithStringKey`, new, keyed by payer key. `TryClaimAsync(campaignId, userId, nowUtc)` returns `Claimed | HeldByThisAccount | HeldByAnotherAccount`. Any prior claim blocks every `OncePerPayer` campaign, for life.
- `ILoyaltyPointsAccountGrain.SetPayerKeyAsync(payerKey)` sets the key once; first seen wins. `GrantCampaignCreditAsync(GrantCampaignCreditRequest)` replaces the four-parameter overload (three callers: issuer, admin mutation, tests).
- `UserCreatedEventHandler` stamps the key from `evt.Email` beside the existing creation-date stamp. Event Grid gives no ordering against the first wallet read, so `SignupCampaignGrantIssuer` passes the token email as a fallback and the admin mutation passes the aggregate's email.

```csharp
// LoyaltyPointsAccountGrain.GrantCampaignCreditAsync, after every existing refusal, before the ledger append
if (request.OncePerPayer)
{
    var payerKey = _state.State.PayerKey ?? request.PayerKeyFromCaller;
    if (payerKey == null)
        return GrantCreditResult.Deferred(request.CampaignId);

    var outcome = await GrainFactory.GetGrain<IGrantedCreditPayerGrain>(payerKey)
        .TryClaimAsync(request.CampaignId, userId, UtcNow());
    if (outcome == PayerClaimOutcome.HeldByAnotherAccount)
    {
        _state.State.PayerGateRefusedCampaignIds.Add(request.CampaignId);
        await _state.WriteStateAsync();
        return GrantCreditResult.Refused(request.CampaignId, PayerAlreadyHadGrant);
    }
    _state.State.PayerKey ??= payerKey;
}
```

## Infrastructure
| Concern | Change |
|---|---|
| Grain storage | New `GrainStorage.GrantedCreditPayer` constant with its own container. Sharing `LoyaltyPointsAccount` would poison it under the Orleans 10 legacy provider (the AB#17436 sandbox outage). |
| Terraform | `GrainStorage-GrantedCreditPayer` (`/PartitionKey`) in all five `environments/*/shared/vars.auto.tfvars`. Separate PR from `main`, applied to sandbox before the consolidator deploy. |
| Config | None. `GrantedCreditCampaign.OncePerPayer` already parses from App Configuration and is read by nothing today. |
| Events | None new. |

## API
No schema change. `grantLoyaltyPointsCampaignCredit` throws `LoyaltyPointsInvalidAmendmentException` for `Refused` (the grain's reason) and for `Deferred` ("payer identity is not yet known, retry shortly"). `visionaryPoints` returns balance 0 and an empty `grantedCredits` for a refused payer. Snapshot untouched.

## Tests
| Project | Class | Cases |
|---|---|---|
| Domain.Subscription.Tests | PayerKeyTests | trim and case, plus suffix removed, dots kept, no @ is null, equal roots hash equal |
| Grains.Tests | GrantedCreditPayerGrainTests | Claimed, HeldByThisAccount, HeldByAnotherAccount, second campaign id still held |
| Grains.Tests | LoyaltyPointsAccountGrainTests | SetPayerKey idempotent, fallback key persisted on claim |
| API.Test | GetLoyaltyPointsOncePerPayerTests | plus alias grants nothing; case variant grants nothing; dotted root granted; different root granted; flagless campaign credits repeat payer; stamped key with email-less token grants; no key defers then grants once stamped; refusal cached, no ledger or payer grain call; first-invoice refusal leaves key free; same account twice grants once |
| API.Test | GrantLoyaltyPointsCampaignCreditTests | repeat payer throws payer rule; no key and no aggregate throws deferred; existing signup-grant cases stamp a key first |
| AcceptanceTests | LoyaltyPointsGrantedCredit.feature | the three scenarios above; second member slot in the steps class; seed step retries while deferred |

Shared infra: `TestUser.Email` and an `AcmeEmail` header in `GraphQLTestClient` and `TestAuthHandler`. Additive; unset keeps `{userId}@test.local`, which other suites assert on.

## Decisions
- Gate inside the account grain, not the issuer, so the admin mutation follows the same rule and acceptance tests can reach it. No bypass: an admin crediting a known repeat payer uses a flagless campaign.
- A payer grain over an EF Cosmos entity. One activation per key serialises two accounts racing for the same root without 409 handling. Both need a tfvars change.
- First key wins. Claiming under a fallback pins it, so a later stamp cannot change what an account was judged by. A linked account whose token and connector emails differ is judged by whichever arrived first.
- Deferred is its own outcome, never success-shaped.
- Once per payer for life, not once per campaign.

## Risks and rollout
- Email is the only signal. Dot tricks and second addresses beat it by design; AB#17445 catches those at checkout. A household on plus aliases is an accepted false positive.
- Terraform first: without the container the first flagged grant throws on storage open.
- Stacked on PR 3081, base set by hand. Do not `gh stack link`: it is a sibling of PR 3087 and linking retargets sibling bases. Expect a small conflict with 3087 in `GrainStorage.cs` and the tfvars.
- Grants already issued on sandbox and dev are not retro-claimed; they stop at already-applied. Prod has none.
- Sandbox smoke: a fresh Gmail signup via the campaign link shows 1,000; its `+rv` alias shows 0 and no welcome modal; then the `ENV=sand` acceptance run.

## Open questions
1. Include the durable sign-in identity in this story? B2C computes `issuerUserId` (Google id, Apple sub) but never sends it to `EnrichToken`.
   - [x] **Defer to a follow-up after AB#17445.** Email root only for now; the refinement note allows it.
   - [ ] **Include now.** Adds a B2C policy PR, a connector model field and a second payer key to this stack.
2. Backfill payer claims for grants PR 3081 already issued on sandbox and dev? Those accounts never reach the gate, so their keys stay unclaimed.
   - [x] **No backfill.** Test accounts only; a tester re-signing up with an alias being credited is acceptable there.
   - [ ] **One-off processor.** Walk ledger Grant rows, resolve each aggregate email, claim the key. Precedent: `BackfillUserAnniversariesProcessor`.
3. Anything else to preserve or avoid?
```
