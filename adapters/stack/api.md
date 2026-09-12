# API style

This field changes what the plan's API section names for each new or changed
endpoint, and what the review's Contracts and coordination table carries: the route or
schema delta, the request and response shape, and which client has to move to match
it.

## minimal-api

**Plan** - Name each new or changed route: method, path, request and response types,
and the status codes it can return. Fence the route list so the reviewer can scan it
without reading the handler bodies. Say whether validation happens in the route or in
a filter.

**Review** - One row per route added or changed: the path, the shape of the request
and response, and which client, frontend or another service, has to move to match it.
A status code change is itself a coordination row, since a client may branch on the
old code.

**Common findings**
- Business logic written inline in the route handler instead of delegated to
  Application.
- Request validation missing or duplicated between a filter and the handler.
- Inconsistent status codes for the same failure across routes.

## controllers

**Plan** - Name each new or changed action: controller, HTTP method, route template,
request and response types, and the status codes returned. Fence the action list. Say
which filters or attributes, authorization or validation, apply and whether they are
new.

**Review** - One row per action added or changed: the route, the request and response
shape, and which client has to move to match it. A model binding change, a new
required field or a renamed property, is its own coordination row.

**Common findings**
- Fat controllers with business logic instead of a thin call into Application.
- A response DTO that mirrors a domain or persistence type one-to-one instead of
  shaping what the client actually needs.
- Authorization attributes missing on a new action that clearly needs them.

## graphql

**Plan** - Carry the SDL delta as a fence: the types, fields and arguments added or
changed, plus any new query or mutation. Before naming a new type, enum or input,
check the other federated services' schemas for the same name; the gateway renames the
losing side when two services publish the same type name, breaking frontend queries
without warning. Prefer a service-prefixed name for anything generic.

**Review** - One row per type or field changed: the SDL delta, and which client query
has to move to match it. A type-name collision, once found, is its own row naming both
services and which keeps the original name.

**Common findings**
- A new type or enum with a generic name that already exists in another service.
- A nullable field that should be non-null, or the reverse, forcing defensive checks
  on every client.
- A resolver doing N+1 data fetching instead of using a batching data loader.

## grpc

**Plan** - Carry the proto delta as a fence: the service, the RPC methods added or
changed, and the request and response message shapes. Say whether a method is unary or
streaming, since that changes both the client contract and the review's coordination
row.

**Review** - One row per RPC changed: the proto delta, and which client has to
regenerate its stubs and move to match it. A field number change or a removed field is
its own row, since either breaks wire compatibility.

**Common findings**
- A field renumbered or removed instead of reserved, breaking wire compatibility with
  older clients.
- A required field added to a message that is not backward compatible with already
  deployed clients.
- A streaming method used where a client actually only needs a single
  request-response.
