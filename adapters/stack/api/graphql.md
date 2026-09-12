# GraphQL

## Plan: what to name

API carries the SDL delta as a fence: the types, fields and arguments added or
changed, plus any new query or mutation. Before naming a new type, enum or input,
check the other federated services' schemas for the same name; the gateway renames the
losing side (`Original` becomes `SCHEMANAME_Original`) when two services publish the
same type name, breaking frontend queries without warning. Prefer a service-prefixed
name for anything generic.

## Review: contracts and coordination

Contracts and coordination gets one row per type or field changed: the SDL delta, and
which client query has to move to match it. A type-name collision, once found, is its
own row naming both services and which keeps the original name.

## Common findings

- A new type or enum with a generic name that already exists in another service.
- A nullable field that should be non-null, or the reverse, forcing defensive checks
  on every client.
- A mutation returning the mutated entity directly instead of a payload type with an
  errors field.
- A resolver doing N+1 data fetching instead of using a batching data loader.
- A breaking field removal or rename with no deprecation period.
