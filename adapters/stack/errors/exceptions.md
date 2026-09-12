# Exceptions

## Plan: what to name

Application names each new or changed exception type used for a failure case, and
where it is caught: at the API boundary, or closer to the source. API says how each
exception type maps to a status code and error payload.

## Review: contracts and coordination

Contracts and coordination gets one row when a new exception type crosses the API
boundary in a new way: what status code it now produces, and which client has to
handle it. A change to an existing exception's status code mapping is its own row.

## Common findings

- A generic exception caught and rethrown or swallowed instead of a specific type
  handled deliberately.
- Exceptions used for expected, non-exceptional control flow instead of a Result or a
  simple return value.
- An exception message containing information a client should not see, such as
  internal paths or connection strings.
- Inconsistent status code mapping for the same exception type across different
  endpoints.
- A catch block that logs and returns null instead of handling the specific failure or
  letting it propagate.
