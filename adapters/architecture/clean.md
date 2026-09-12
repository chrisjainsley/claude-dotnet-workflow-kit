# Clean Architecture

## Plan sections

The plan runs in dependency order, from the requirement outward through the layers:

- Context: parent feature, siblings, area, design links.
- Requirement: the change in product terms plus one concrete example.
- Specs: the Gherkin scenarios that become acceptance tests.
- Domain: aggregates, value objects, events and enums, as signatures.
- Application: handlers, use cases and service interfaces, with their guarantees.
- Infrastructure: persistence, messaging, configuration and external services, as a table.
- API: the contract delta, in the API style's own notation.
- Tests: one row per test class and case.
- Decisions: what was chosen over what, and why.
- Risks and rollout: what can go wrong and how QA verifies it.
- Open questions: anything left for the reviewer to settle.

## Review slices

The review's Changes tables group files under: Domain, Application, Infrastructure,
API, Tests. Examples: a new aggregate root and a value object land under Domain; a new
handler and its interface land under Application. A DbContext change and a migration
land under Infrastructure; a new endpoint or resolver lands under API.

## What the reviewer looks for

- Anemic domain models: entities that are plain data holders with logic pushed into a
  service instead of the aggregate.
- Infrastructure types (DbContext, HTTP clients, SDK types) referenced from Domain or
  Application.
- Application handlers that talk to a database or external API directly instead of
  through an interface Infrastructure implements.
- Fat endpoints or resolvers that contain business logic instead of delegating to
  Application.
- Domain events raised but never dispatched, or dispatched from the wrong layer.
- Validation duplicated across layers instead of owned once, closest to the invariant.
- A dependency pointing the wrong way, such as Domain referencing Infrastructure.
