# Data access

This field changes what the plan's Infrastructure section names for schema and query
changes, and what the review's Contracts and coordination table carries for each one:
the migration or schema mechanism, the index or partition implications, and who else
reads the same store.

## ef-core

**Plan** - Name the `DbContext` touched, any new or changed entity configuration, and
the migration it produces. List the migration file and what it does to the schema (add
column, add table, add index). Call out any new index the query needs, since a missing
index is a common regression; say what column set it covers and why.

**Review** - One row per migration: the table or column it changes, and what has to
run it, a deploy step or a manual backfill for existing rows. A schema change that
another service reads directly gets its own row naming that service.

**Common findings**
- A query that will translate to client-side evaluation instead of SQL, found only at
  runtime.
- A missing index behind a new `Where` or `OrderBy` that will be slow at scale.
- Tracking left on for a read-only query instead of `AsNoTracking`.

## dapper

**Plan** - Name the raw SQL each new or changed query runs, the parameters it takes,
and the mapped return type. There is no migration tool built in, so name the schema
change as its own script and where it runs, a migration folder or a deploy step,
alongside the query.

**Review** - One row per schema change: the table or column affected, the script that
applies it, and what has to run it before the dependent code deploys. A query shared
by more than one service gets a row naming the other consumer.

**Common findings**
- SQL built by string concatenation instead of parameters, an injection risk.
- No index behind a new predicate, found only under load.
- A multi-statement operation with no transaction wrapping it.

## cosmos

**Plan** - Name the container, the partition key path, and any change to the document
shape for each entity touched. Call out a new query's filter and sort columns
together, since a filter plus a sort on different properties needs a composite index,
and that index change is itself a deploy step.

**Review** - One row per container: the partition key, any indexing policy change, and
the request unit impact of a new query pattern. A document shape read by more than one
service gets a row naming that consumer, since there is no schema to enforce
compatibility.

**Common findings**
- A cross-partition query where a partition-key filter would have avoided it.
- A missing composite index behind a filter-plus-sort query, returning an error only
  in a real environment, never in an in-memory test.
- Optimistic concurrency (ETag) ignored on a read-modify-write, risking lost updates.

## other

**Plan** - Name the storage technology used, the entity or table each change touches,
and how the schema change is applied and rolled back. Without a shared convention, be
explicit about the mechanism, a script, a tool-specific migration, or a manual step,
since the plan is the only place that mechanism gets recorded.

**Review** - One row per schema or storage change: what changed, how it is applied,
and who else reads or writes the same store. Treat every claim about ordering or
compatibility as something to spell out rather than assume, since no shared tooling
enforces it.

**Common findings**
- A schema change with no documented rollback path.
- No documented locking or concurrency model for concurrent writers.
- A migration step that is not idempotent, unsafe to re-run after a partial failure.
