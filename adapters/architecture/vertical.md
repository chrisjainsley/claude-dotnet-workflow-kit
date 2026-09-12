# Vertical Slice

Vertical slice architecture is defined in this kit and exercised by
`tests/fixtures/plan-vertical.md`, which the checker and builder both run against in
CI alongside the `clean` fixture.

## Plan sections

The plan still runs from the requirement outward, with the middle four sections
replaced by one slice-shaped path:

- Context: parent feature, siblings, area, design links.
- Requirement: the change in product terms plus one concrete example.
- Specs: the Gherkin scenarios that become acceptance tests.
- Slice: the feature folder, its request and handler, in one place instead of split
  across layers.
- Persistence: what the slice reads or writes and how.
- Integration: other services or external calls the slice makes.
- Endpoint: the contract delta for the slice's own endpoint.
- Tests: one row per test class and case.
- Decisions: what was chosen over what, and why.
- Risks and rollout: what can go wrong and how QA verifies it.
- Open questions: anything left for the reviewer to settle.

## Review slices

The review's Changes tables group files under: Slice, Persistence, Integration,
Endpoint, Tests. Examples: the feature's request, handler and validator land under
Slice; a repository call or a query lands under Persistence. A call to another service
lands under Integration; the minimal API route or controller action lands under
Endpoint.

## What the reviewer looks for

- A slice reaching into another slice's folder instead of duplicating the small amount
  it needs.
- Shared logic pulled into a generic base class that starts coupling unrelated slices
  together.
- Persistence or integration code left inline in the endpoint instead of a named,
  testable step.
- A slice growing enough internal layering that it is really a small clean
  architecture in disguise, unacknowledged as such.
- Tests that exercise the whole slice through the endpoint only, with no coverage of
  the handler in isolation.
