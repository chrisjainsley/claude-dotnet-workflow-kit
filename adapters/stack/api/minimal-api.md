# Minimal API

## Plan: what to name

API names each new or changed route: method, path, request and response types, and the
status codes it can return. Fence the route list so the reviewer can scan it without
reading the handler bodies. Say whether validation happens in the route or in a
filter.

## Review: contracts and coordination

Contracts and coordination gets one row per route added or changed: the path, the
shape of the request and response, and which client, frontend or another service, has
to move to match it. A status code change is itself a coordination row, since a client
may branch on the old code.

## Common findings

- Business logic written inline in the route handler instead of delegated to
  Application.
- Request validation missing or duplicated between a filter and the handler.
- A response shape that leaks an internal or persistence type instead of a dedicated
  DTO.
- Inconsistent status codes for the same failure across routes.
- Route grouping or versioning conventions not followed, making the route hard to find
  later.
