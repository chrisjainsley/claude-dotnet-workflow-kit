# Wolverine

## Plan: what to name

Infrastructure names each new or changed message type, the handler that processes it,
and the transport binding, queue or topic, it is wired to. Say whether the handler
participates in an outbox alongside a persistence write, since that is what makes the
publish transactional.

## Review: contracts and coordination

Contracts and coordination gets one row per message type: its shape, the transport it
is wired to, and which other services or handlers consume it. A message shape change
is its own row naming every handler that has to move together.

## Common findings

- A handler that writes to persistence and publishes a message without an outbox,
  risking a message sent for a write that later rolls back.
- A message type with no explicit transport binding, relying on convention that
  changes with deployment.
- Cascading messages from a handler that make the failure path hard to follow.
- A handler with no idempotency check for a message that can be redelivered.
- Business logic in the handler instead of delegated to Application.
