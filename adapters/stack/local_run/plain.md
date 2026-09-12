# Plain

## QA stage

Start each service directly with `dotnet run` from its project directory, in the order
its dependencies need, a local database or cache before the API that reads it. The QA
report's Environment line reads `local (plain)` with the list of projects started, so a
re-tester knows exactly what to launch.

## Common issues

- A dependency, a local database or a cache, not running because there is no
  orchestrator to start it automatically.
- Configuration values that differ between developers' machines with no shared source
  of truth, making a scenario pass for one person and fail for another.
- Services started in the wrong order, so the first request to a dependent service
  fails before its dependency is ready.
- Ports colliding with another service already running locally.
