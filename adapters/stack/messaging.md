# Messaging

This field changes what the plan's Infrastructure section names for each message
contract, and what the review's Contracts and coordination table carries: the topic or
queue, the consumer or handler, and which other services move together on a shape
change.

## masstransit

**Plan** - Name each new or changed message contract, the event or command type, the
topic or queue it publishes to, and the consumer that handles it. Say which binary or
project the contract and its consumer live in, since a consumer registered in the
wrong host will silently never receive the message.

**Review** - One row per message contract: its shape, the topic it publishes to, and
which other services consume it. A contract change, a new required property or a
renamed field, is its own row naming every consumer that has to move together.

**Common findings**
- A new event not mapped to the topic its consumers actually subscribe to.
- A consumer with no retry or error queue configured, dropping failures silently.
- A publish call left unawaited, losing the message on an unhandled exception.

## wolverine

**Plan** - Name each new or changed message type, the handler that processes it, and
the transport binding, queue or topic, it is wired to. Say whether the handler
participates in an outbox alongside a persistence write, since that is what makes the
publish transactional.

**Review** - One row per message type: its shape, the transport it is wired to, and
which other services or handlers consume it. A message shape change is its own row
naming every handler that has to move together.

**Common findings**
- A handler that writes to persistence and publishes a message without an outbox,
  risking a message sent for a write that later rolls back.
- A message type with no explicit transport binding, relying on convention that
  changes with deployment.
- A handler with no idempotency check for a message that can be redelivered.

## service-bus

**Plan** - Name each new or changed message, the queue or topic and subscription it
uses, and the processor that reads it. Say whether the queue has a dead-letter queue
configured and what reads it, since an unmonitored dead-letter queue is where failed
messages go quiet.

**Review** - One row per queue or topic changed: the message shape, the subscription
filter if any, and which other services read from it. A change to a topic's
subscription rules is its own row, since it silently changes who receives what.

**Common findings**
- No dead-letter queue monitoring, so failures accumulate unnoticed.
- A message handler with no idempotency check for at-least-once delivery.
- A lock duration too short for the handler's actual processing time, causing message
  lock loss.

## none

**Plan** - There is no message broker in this stack. Infrastructure has nothing to
name here; if the ticket looks like it needs asynchronous processing, say so as an
Open question rather than reaching for a broker the profile does not declare.

**Review** - No row for messaging. If the diff introduces a queue, topic or background
worker anyway, that is itself a finding: either the profile is stale and needs
updating, or the change should not have introduced messaging without discussion.

**Common findings**
- A background task or fire-and-forget call used in place of a proper queue, losing
  work on process restart.
- Polling introduced where an event would have been simpler, because messaging was
  assumed unavailable.
- A synchronous call chain standing in for what should be an asynchronous handoff,
  coupling two services' uptime together.
