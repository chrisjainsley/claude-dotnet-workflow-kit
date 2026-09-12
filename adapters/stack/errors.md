# Error handling

This field changes what the plan's Application and API sections name for a failure
case, and what the review's Contracts and coordination table carries when the set of
errors a client can see changes shape.

## result

**Plan** - Name the `Result` or `Result<T>` type each use case returns, and the error
cases it can carry as named values, not raw strings. API says how a failed Result maps
to a status code and payload shape at the boundary.

**Review** - One row when a Result's error cases change: which client branches on the
old set and has to move to match the new one. A new error case added to an existing
Result is a coordination row even when the happy path is unchanged.

**Common findings**
- A Result's success value read without checking `IsSuccess` first.
- An exception thrown alongside a Result type for the same kind of failure,
  inconsistent within one codebase.
- Every failure collapsed into one generic error case, hiding what a caller could
  otherwise branch on.

## exceptions

**Plan** - Name each new or changed exception type used for a failure case, and where
it is caught: at the API boundary, or closer to the source. API says how each
exception type maps to a status code and error payload.

**Review** - One row when a new exception type crosses the API boundary in a new way:
what status code it now produces, and which client has to handle it. A change to an
existing exception's status code mapping is its own row.

**Common findings**
- A generic exception caught and rethrown or swallowed instead of a specific type
  handled deliberately.
- Exceptions used for expected, non-exceptional control flow instead of a Result or a
  simple return value.
- A catch block that logs and returns null instead of handling the specific failure or
  letting it propagate.
