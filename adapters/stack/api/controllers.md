# Controllers

## Plan: what to name

API names each new or changed action: controller, HTTP method, route template,
request and response types, and the status codes returned. Fence the action list. Say
which filters or attributes, authorization or validation, apply and whether they are
new.

## Review: contracts and coordination

Contracts and coordination gets one row per action added or changed: the route, the
request and response shape, and which client has to move to match it. A model binding
change, a new required field or a renamed property, is its own coordination row.

## Common findings

- Fat controllers with business logic instead of a thin call into Application.
- Model binding validated by convention only, with no explicit check for the domain
  rule it is supposed to protect.
- A response DTO that mirrors a domain or persistence type one-to-one instead of
  shaping what the client actually needs.
- Inconsistent status codes or error shapes across actions for the same kind of
  failure.
- Authorization attributes missing on a new action that clearly needs them.
