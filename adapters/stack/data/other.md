# Other

## Plan: what to name

Infrastructure names the storage technology used, the entity or table each change
touches, and how the schema change is applied and rolled back. Without a shared
convention, be explicit about the mechanism, a script, a tool-specific migration, or a
manual step, since the plan is the only place that mechanism gets recorded.

## Review: contracts and coordination

Contracts and coordination gets one row per schema or storage change: what changed,
how it is applied, and who else reads or writes the same store. Treat every claim
about ordering or compatibility as something to spell out rather than assume, since
there is no shared tooling enforcing it.

## Common findings

- A schema change with no documented rollback path.
- No documented locking or concurrency model for concurrent writers.
- A migration step that is not idempotent, unsafe to re-run after a partial failure.
- Connection or credential handling duplicated instead of centralized in one place.
- A query pattern with no stated performance expectation, so a regression has nothing
  to compare against.
