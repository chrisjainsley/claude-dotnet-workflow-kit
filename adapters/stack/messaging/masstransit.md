# MassTransit

## Plan: what to name

Infrastructure names each new or changed message contract, the event or command type,
the topic or queue it publishes to, and the consumer that handles it. Say which
binary or project the contract and its consumer live in, since a consumer registered
in the wrong host will silently never receive the message.

## Review: contracts and coordination

Contracts and coordination gets one row per message contract: its shape, the topic it
publishes to, and which other services consume it. A contract change, a new required
property or a renamed field, is its own row naming every consumer that has to move
together.

## Common findings

- A new event not mapped to the topic its consumers actually subscribe to.
- A consumer with no retry or error queue configured, dropping failures silently.
- A message contract changed in a way that breaks an existing consumer still on the
  old shape.
- Business logic executed directly in the consumer instead of delegated to
  Application.
- A publish call left unawaited, losing the message on an unhandled exception.
