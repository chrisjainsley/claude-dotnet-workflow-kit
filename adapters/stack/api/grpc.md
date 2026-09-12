# gRPC

## Plan: what to name

API carries the proto delta as a fence: the service, the RPC methods added or changed,
and the request and response message shapes. Say whether a method is unary or
streaming, since that changes both the client contract and the review's coordination
row.

## Review: contracts and coordination

Contracts and coordination gets one row per RPC changed: the proto delta, and which
client has to regenerate its stubs and move to match it. A field number change or a
removed field is its own row, since either breaks wire compatibility.

## Common findings

- A field renumbered or removed instead of reserved, breaking wire compatibility with
  older clients.
- A required field added to a message that is not backward compatible with already
  deployed clients.
- Error information returned as a plain string instead of the status details a client
  can branch on.
- A streaming method used where a client actually only needs a single request-response.
- Generated stubs checked in and edited by hand instead of regenerated from the proto.
