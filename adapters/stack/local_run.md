# Local run

This field is not about naming or contracts, it is about getting the system running
to gather QA evidence, so it changes what the QA report's Environment line says and
what the review flags as a run-style failure rather than a regression.

## aspire

**QA stage** - Start the system through its Aspire AppHost project: `dotnet run
--project <Service>.AppHost`. The dashboard URL prints on startup and shows every
resource, APIs, processors and containers, with its logs and traces in one place. The
QA report's Environment line reads `local (Aspire)` with the AppHost project name, so a
re-tester knows which stack to start.

**Common issues**
- Docker Desktop not running before a container resource, a queue emulator or a
  database, starts, failing the whole AppHost.
- A resource that needs a one-time tool install, a functions runtime or a CLI, missing
  from the machine, failing silently until the dashboard is checked.
- Stale state in a previous run's data volume causing a resource to behave as if
  already provisioned.

## docker

**QA stage** - Start the system with `docker compose up`, or the project's equivalent
compose file, then wait for the health checks each container defines before hitting an
endpoint. The QA report's Environment line reads `local (Docker)` with the compose
file name, so a re-tester starts the same set of containers.

**Common issues**
- A container built from a stale image because a rebuild step was skipped after a
  code change.
- Environment variables or connection strings pointing at a different container's
  default port than the one actually mapped.
- A dependent container starting before the service it depends on is ready, since
  compose's own ordering does not wait for health.

## plain

**QA stage** - Start each service directly with `dotnet run` from its project
directory, in the order its dependencies need, a local database or cache before the
API that reads it. The QA report's Environment line reads `local (plain)` with the
list of projects started, so a re-tester knows exactly what to launch.

**Common issues**
- A dependency, a local database or a cache, not running because there is no
  orchestrator to start it automatically.
- Configuration values that differ between developers' machines with no shared source
  of truth, making a scenario pass for one person and fail for another.
- Services started in the wrong order, so the first request to a dependent service
  fails before its dependency is ready.
