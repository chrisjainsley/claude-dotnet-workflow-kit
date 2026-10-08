---
title: Keep me signed in
ticket: AB#17521
state: merged
pr: https://github.com/example-org/example-repo/pull/3103
branch: feat/AB#17521/enable-keep-me-signed-in
base: dev
commits: 1 squash, adb1dfbed
files: 3 changed, +2 / -7
ci: green
deployed: sandbox tenant via run 34390487629 on 2026-09-09, not dev
size: standard
date: 2026-09-11
---

## Verdict

Merged on 2026-09-10. Web sign-in gains the option and a 90 day session. Mobile gains neither, so one acceptance criterion is undelivered. No plan document exists, so the rows below are the ticket's acceptance criteria.

| Metric | Value | Note |
|---|---|---|
| Acceptance | 0/0 | no suite covers B2C sign-in |
| Manual QA | 0/0 | no credentialed session on the sandbox tenant |
| Findings open | 2 | highest high |
| AC covered | 10/11 | mobile session dropped, sign-out web only |

## Plan versus delivered

| Item | Status | Note |
|---|---|---|
| The option is offered but not pre-selected | done | |
| Declining it keeps today's behaviour | done | |
| A web member is not asked to sign in for 90 days | done | |
| A mobile member is not asked to sign in for 90 days | dropped | mobile relying party untouched |
| A kept session survives closing the browser | done | |
| The daily refresh returns the member without credentials | done | |
| Signing out clears the kept session | changed | web only, native sign-out skips `end_session` |
| The option does not apply to a social provider | done | |
| Password reset still signs the member in | done | |
| Sign-up still signs the new member in | done | |
| A kept session survives a password reset | done | |

## Changes

Only the web relying party gained `KeepAliveInDays`; the mobile policy is untouched.

```flowmap
lanes: Infrastructure
rows: Web sign-in, Mobile sign-in

node web-rp: AccountLinkSignUpOrSignIn relying party
  lane: Infrastructure
  row: Web sign-in
  file: Acme.App.Services.User.AzureB2C/Policies/B2C_1A_SIGNUP_SIGNIN.xml
  kind: policy
  status: modified
  note: tenant SSO cookie kept 90 days

node web-tp: SelfAsserted LocalAccountSignin Email ForgotPassword
  lane: Infrastructure
  row: Web sign-in
  file: Acme.App.Services.User.AzureB2C/Policies/B2C_1A_ACCOUNTLINK_EXTENSIONS.xml
  kind: technical profile
  status: modified
  note: renders the remember-me box

node web-sso: SingleSignOn KeepAliveInDays 90
  lane: Infrastructure
  row: Web sign-in
  file: Acme.App.Services.User.AzureB2C/Policies/B2C_1A_SIGNUP_SIGNIN.xml
  kind: session
  status: modified

node mobile-rp: MobileSignInOnly relying party
  lane: Infrastructure
  row: Mobile sign-in
  file: Acme.App.Services.User.AzureB2C/Policies/B2C_1A_MOBILE_SIGNIN.xml
  kind: policy
  status: modified
  note: dead parameter removed

node mobile-tp: SelfAsserted LocalAccountSignin Email
  lane: Infrastructure
  row: Mobile sign-in
  kind: technical profile
  status: context

node mobile-sso: SingleSignOn rolling 86400 s
  lane: Infrastructure
  row: Mobile sign-in
  kind: session
  status: context

test web-tests: no B2C test host
  covers: web-rp
  status: missing

web-rp -> web-tp
web-tp -> web-sso: enableRememberMe
mobile-rp -> mobile-tp
mobile-tp -> mobile-sso
```

### User Service, Azure B2C policies

| Slice | File | Change |
|---|---|---|
| Infrastructure | `Acme.App.Services.User.AzureB2C/Policies/B2C_1A_SIGNUP_SIGNIN.xml` | web relying party keeps the tenant SSO cookie for 90 days |
| Infrastructure | `Acme.App.Services.User.AzureB2C/Policies/B2C_1A_ACCOUNTLINK_EXTENSIONS.xml` | web sign-in profile renders the option |
| Infrastructure | `Acme.App.Services.User.AzureB2C/Policies/B2C_1A_MOBILE_SIGNIN.xml` | dead `setting.showKeepMeSignedIn` parameter removed |
| Tests | none | B2C policy XML has no test host in this repo |

B2C caps `SessionExpiryInSeconds` at 86400 and ignores `refresh_token_lifetime_secs` for SPAs, so `KeepAliveInDays` is the only lever past 24 hours.

#### The web relying party trades a dead parameter for the real session lever

```diff
     <UserJourneyBehaviors>
-      <SingleSignOn Scope="Tenant" />
-      <ContentDefinitionParameters>
-        <Parameter Name="setting.showKeepMeSignedIn">true</Parameter>
-      </ContentDefinitionParameters>
+      <SingleSignOn Scope="Tenant" KeepAliveInDays="90" />
       <ScriptExecution>Allow</ScriptExecution>
     </UserJourneyBehaviors>
```

#### The box is enabled on the one profile the web journey calls

```diff
         <TechnicalProfile Id="SelfAsserted-LocalAccountSignin-Email-ForgotPassword">
           <Metadata>
             <Item Key="setting.forgotPasswordLinkOverride">ForgotPasswordExchange</Item>
+            <Item Key="setting.enableRememberMe">true</Item>
```

`AccountLinkSignUpOrSignIn` calls that profile; `MobileSignInOnly` calls `SelfAsserted-LocalAccountSignin-Email`, which was not edited, under a relying party still set to a rolling 86400 second session.

## Contracts and coordination

| Concern | Change | Action |
|---|---|---|
| GraphQL schema | none | |
| Events | none | |
| Storage | none | |
| Config | policy XML only, no App Configuration keys | |
| Migrations | none | |
| Tenants | sandbox applied 2026-09-09, no dev run since the merge, stg and prod ride the release digest lane | dispatch for dev, then re-check each tenant |
| Client apps | native sign-out skips B2C `end_session` | web-client fix before mobile gets the option |
| Type-name collisions | not applicable | |

## Findings

| Severity | Location | Finding | Status | Note |
|---|---|---|---|---|
| high | `B2C_1A_MOBILE_SIGNIN.xml:583` | the mobile relying party has no `KeepAliveInDays` and its journey calls a profile without the option, so mobile members get neither if the app signs in through this policy | open | which policy the app calls is not verifiable from this repo; the ticket assumes one serves both |
| medium | `web-client useLogoutRedirect.tsx` | native sign-out skips `end_session`, so a persistent cookie would outlive log out once mobile gets the option | open | flagged in the PR body, not fixed |
| low | `B2C_1A_ACCOUNTLINK_EXTENSIONS.xml:457` | nothing automated covers the behaviour | accepted | policy XML has no test host; deploy smoke is the only gate |
| info | `B2C_1A_SIGNUP_SIGNIN.xml:12` | `SessionExpiryType` and `SessionExpiryInSeconds` left at their defaults | accepted | members who decline keep today's rolling 24 hour session |

## QA report

**No QA run.** This review holds no evidence from a running system.

**Environment:** sandbox tenant | **Date:** 2026-09-11 | **Test users:** none, no credentialed session

**Not covered:** all eleven acceptance criteria. The option rendering and pre-selection state need a browser on the sandbox sign-in page. Session length, browser restart, refresh without a prompt and sign-out need a credentialed sign-in and a clock. Social sign-in, password reset and sign-up need a regression pass on the shared sign-in page. The PR body reports the author saw the option unticked on the sandbox tenant, which is a claim, not evidence. Deploy run 34390487629 proves only that the bundle applied and passed smoke.

## Rollout

- [ ] Confirm the sandbox tenant still carries this bundle after later B2C batches
- [ ] Dispatch `user-azure-b2c.yml` for dev, no run followed the merge
- [ ] Promote to qa, stg and prod, then re-check each tenant
- [ ] Decide mobile: extend `B2C_1A_MOBILE_SIGNIN`, or narrow the ticket to web
- [ ] Raise the web-client sign-out fix before mobile gets a persistent cookie
- [ ] QA: 90 day, browser restart and sign-out checks with real credentials

## Decision

Approve for web, raise a follow-up for mobile. The work item should not close on this PR alone.

## Walkthrough

1. `Verdict` This change merged on the tenth of September. Web members can now stay signed in for ninety days. Mobile members cannot, so ten of eleven acceptance criteria are delivered.
2. `@web-rp` The whole change is policy XML. The web relying party now keeps the tenant sign-in cookie for ninety days, through the keep alive setting.
3. `@mobile-rp` The mobile relying party only lost a dead parameter. Its journey still calls a profile without the option, under a rolling one day session.
4. `Findings > B2C_1A_MOBILE_SIGNIN` That gap is the high finding. Which policy the mobile app calls is not verifiable from this repository.
5. `Findings > useLogoutRedirect` The other open finding is sign-out. Native sign-out skips the end session call, so a kept cookie would outlive log out once mobile gets the option.
6. `QA report` Nothing has run against a live tenant yet. All eleven criteria sit under not covered.
7. `Rollout` Next, dispatch the dev deployment, decide what happens to mobile, and get real credentials for the ninety day checks.
8. `Decision` The recommendation is to approve for web and raise a follow-up for mobile. The work item should not close on this PR alone.
