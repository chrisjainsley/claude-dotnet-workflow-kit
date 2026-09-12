# Cosmos DB

## Plan: what to name

Infrastructure names the container, the partition key path, and any change to the
document shape for each entity touched. Call out a new query's filter and sort columns
together, since Cosmos needs a composite index for a filter plus a sort on different
properties, and that index change is itself a deploy step.

## Review: contracts and coordination

Contracts and coordination gets one row per container: the partition key, any indexing
policy change, and the request unit impact of a new query pattern. A document shape
read by more than one service needs a row naming that consumer, since Cosmos has no
schema to enforce compatibility.

## Common findings

- A cross-partition query where a partition-key filter would have avoided it.
- A missing composite index behind a filter-plus-sort query, returning a 400 only in a
  real environment, never in an in-memory test.
- A document growing past the container's item size limit through unbounded array
  growth.
- Optimistic concurrency (ETag) ignored on a read-modify-write, risking lost updates.
- Indexing policy left at index-everything, inflating request unit cost for a
  container with wide documents.
