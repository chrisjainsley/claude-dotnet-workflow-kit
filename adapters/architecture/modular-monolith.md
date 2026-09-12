# Modular Monolith

Builds on Clean Architecture: the plan sections and review slices are identical to
`adapters/architecture/clean.md`. This page adds the module-boundary rules a modular
monolith asks for on top.

## Plan sections

Same order as Clean Architecture: Context, Requirement, Specs, Domain, Application,
Infrastructure, API, Tests, Decisions, Risks and rollout, Open questions. Name the
owning module in Context, and note in Infrastructure whether the change adds or
changes a module's public contract.

## Review slices

Same as Clean Architecture: Domain, Application, Infrastructure, API, Tests. Within
each slice, group by module when a change touches more than one: a new type inside one
module's Domain folder is one row, and a change to another module's public interface is
a separate row that needs that module's owner to sign off.

## What the reviewer looks for

- A module reaching into another module's internal namespace instead of its published
  public contract.
- A shared database table written by more than one module, instead of each module
  owning its own schema.
- A public contract (an interface, a DTO, an event) changed in a way that breaks
  another module without a note in Contracts and coordination.
- Anemic domain models and infrastructure types leaking into Domain, as in Clean
  Architecture.
- A new dependency between modules added without updating the module's declared
  dependency list.
- Fat endpoints that reach across module boundaries instead of calling the owning
  module's own entry point.
- A domain event consumed directly by another module's internals instead of through
  that module's own handler.
