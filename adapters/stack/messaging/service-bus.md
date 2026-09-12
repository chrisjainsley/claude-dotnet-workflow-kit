# Azure Service Bus

## Plan: what to name

Infrastructure names each new or changed message, the queue or topic and subscription
it uses, and the processor that reads it. Say whether the queue has a dead-letter
queue configured and what reads it, since an unmonitored dead-letter queue is where
failed messages go quiet.

## Review: contracts and coordination

Contracts and coordination gets one row per queue or topic changed: the message
shape, the subscription filter if any, and which other services read from it. A
change to a topic's subscription rules is its own row, since it silently changes who
receives what.

## Common findings

- No dead-letter queue monitoring, so failures accumulate unnoticed.
- A message handler with no idempotency check for at-least-once delivery.
- A subscription filter rule that silently drops messages a consumer expected to
  receive.
- A lock duration too short for the handler's actual processing time, causing message
  lock loss.
- Poison messages retried indefinitely instead of moved to a dead-letter queue after a
  bounded number of attempts.
