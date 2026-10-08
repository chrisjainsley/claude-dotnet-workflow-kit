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

Other sessions may be running AppHosts on the same machine. The kit's mod lists each one
with the session that owns it, in the system prompt and the Sessions pane, and refuses a
kill or a start that would reach another session's. Stop only this session's own AppHost,
by its pid, and never free a port by killing whatever holds it. When a start is refused
for a port, give this worktree ports of its own: add a launch profile with other ports to
the AppHost's `Properties/launchSettings.json` (`applicationUrl` and the
`ASPIRE_DASHBOARD_OTLP_ENDPOINT_URL` and `ASPIRE_RESOURCE_SERVICE_ENDPOINT_URL`
variables) and start with `--launch-profile <name>`. URLs set on the command do not help:
the profile's variables win over them, and from Aspire 13 `--no-launch-profile` is dropped
on the way to the Aspire CLI, which starts the first profile anyway. Endpoint ports fixed in
the AppHost's code (`WithHttpEndpoint(port: ...)`) clash the same way; leave the port out
so Aspire picks a free one. From Aspire 13, starting an AppHost that already runs in the
same folder stops the running copy, so never start one another session runs.

**Common issues**
- Another session's AppHost already holding the dashboard or a resource port, since every
  worktree of a repository starts from the same `launchSettings.json`.
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
