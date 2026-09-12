# No messaging

## Plan: what to name

There is no message broker in this stack. Infrastructure has nothing to name here; if
the ticket looks like it needs asynchronous processing, say so as an Open question
rather than reaching for a broker the profile does not declare.

## Review: contracts and coordination

Contracts and coordination has no row for messaging. If the diff introduces a queue,
topic or background worker anyway, that is itself a finding: either the profile is
stale and needs updating, or the change should not have introduced messaging without
discussion.

## Common findings

- A background task or fire-and-forget call used in place of a proper queue, losing
  work on process restart.
- Polling introduced where an event would have been simpler, because messaging was
  assumed unavailable.
- A synchronous call chain standing in for what should be an asynchronous handoff,
  coupling two services' uptime together.
