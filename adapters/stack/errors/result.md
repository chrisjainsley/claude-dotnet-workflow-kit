# Result pattern

## Plan: what to name

Application names the `Result` or `Result<T>` type each use case returns, and the
error cases it can carry as named values, not raw strings. API says how a failed
Result maps to a status code and payload shape at the boundary.

## Review: contracts and coordination

Contracts and coordination gets one row when a Result's error cases change: which
client branches on the old set and has to move to match the new one. A new error case
added to an existing Result is a coordination row even when the happy path is
unchanged.

## Common findings

- A Result's success value read without checking `IsSuccess` first.
- An exception thrown alongside a Result type for the same kind of failure,
  inconsistent within one codebase.
- Error cases represented as plain strings instead of a closed set the caller can
  switch over.
- A Result silently discarded instead of propagated or logged.
- Every failure collapsed into one generic error case, hiding what a caller could
  otherwise branch on.
