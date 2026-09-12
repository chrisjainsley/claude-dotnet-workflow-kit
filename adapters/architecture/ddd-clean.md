# DDD + Clean Architecture

Builds on Clean Architecture: the plan sections and review slices are identical to
`adapters/architecture/clean.md`, with the same Domain, Application, Infrastructure,
API and Tests headings. This page only adds the aggregate and value-object rules DDD
asks for on top.

## Plan sections

Same order as Clean Architecture: Context, Requirement, Specs, Domain, Application,
Infrastructure, API, Tests, Decisions, Risks and rollout, Open questions. The Domain
section carries more weight here: expect aggregate roots with enforced invariants,
value objects, and domain events named for what happened, not what changed.

## Review slices

Same as Clean Architecture: Domain, Application, Infrastructure, API, Tests. Within
Domain, an aggregate root and its value objects land together; a domain event and its
handler land under Domain and Application respectively.

## What the reviewer looks for

- Anemic domain models, infrastructure types leaking into Domain, and fat endpoints,
  exactly as in Clean Architecture.
- An aggregate exposing a public setter instead of a behavior method that enforces its
  invariant.
- A value object without equality by value, or one that permits construction in an
  invalid state.
- An aggregate boundary crossed directly, such as one aggregate root reaching into
  another's internals instead of referencing it by id.
- A transaction spanning more than one aggregate, instead of one aggregate per
  transaction with eventual consistency between them.
- A domain event named for a technical action ("Updated") instead of a business fact
  ("SubscriptionRenewed").
- Repository interfaces defined per table rather than per aggregate root, with query
  methods that leak persistence concerns into Domain.
