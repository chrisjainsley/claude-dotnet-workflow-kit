# Aspire

## QA stage

Start the system through its Aspire AppHost project: `dotnet run --project <Service>.AppHost`.
The Aspire dashboard URL prints on startup and shows every resource, APIs, processors
and containers, with its logs and traces in one place. The QA report's Environment
line reads `local (Aspire)` together with the AppHost project name, so a re-tester
knows which stack to start.

## Common issues

- Docker Desktop not running before a container resource, a queue emulator or a
  database, starts, failing the whole AppHost.
- A resource that needs a one-time tool install, a functions runtime or a CLI, missing
  from the machine, failing silently until the dashboard is checked.
- Stale state in a previous run's data volume causing a resource to behave as if
  already provisioned.
- Port conflicts with another Aspire stack or a locally running instance of the same
  service.
