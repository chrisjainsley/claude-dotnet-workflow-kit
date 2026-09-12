# EF Core

## Plan: what to name

Infrastructure names the `DbContext` touched, any new or changed entity configuration,
and the migration it produces. List the migration file and what it does to the schema
(add column, add table, add index). Call out any new index the query needs, since a
missing index is a common EF Core regression; say what column set it covers and why.

## Review: contracts and coordination

Contracts and coordination gets one row per migration: the table or column it changes,
and what has to run it, a deploy step or a manual backfill for existing rows. A schema
change that another service reads directly needs its own row naming that service.

## Common findings

- A query that will translate to client-side evaluation instead of SQL, found only at
  runtime.
- A missing index behind a new `Where` or `OrderBy` that will be slow at scale.
- Tracking left on for a read-only query instead of `AsNoTracking`.
- A migration that is not backward compatible with the currently deployed code during
  rollout.
- A navigation property loaded through repeated queries instead of `Include`, an N+1
  pattern.
