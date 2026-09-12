# Dapper

## Plan: what to name

Infrastructure names the raw SQL each new or changed query runs, the parameters it
takes, and the mapped return type. There is no migration tool built in, so name the
schema change as its own script and where it runs, a migration folder or a deploy
step, alongside the query.

## Review: contracts and coordination

Contracts and coordination gets one row per schema change: the table or column
affected, the script that applies it, and what has to run it before the dependent code
deploys. A query shared by more than one service needs a row naming the other
consumer.

## Common findings

- SQL built by string concatenation instead of parameters, an injection risk.
- A query returning more columns than the mapped type uses, wasted transfer.
- No index behind a new predicate, found only under load.
- A multi-statement operation with no transaction wrapping it.
- Mapping code duplicated per query instead of a shared row-to-type mapper.
