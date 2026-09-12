# Docker

## QA stage

Start the system with `docker compose up`, or the project's equivalent compose file,
then wait for the health checks each container defines before hitting an endpoint. The
QA report's Environment line reads `local (Docker)` with the compose file name, so a
re-tester starts the same set of containers.

## Common issues

- A container built from a stale image because a rebuild step was skipped after a
  code change.
- Environment variables or connection strings pointing at a different container's
  default port than the one actually mapped.
- A dependent container starting before the service it depends on is ready, since
  compose's own ordering does not wait for health.
- Volumes left over from a previous run holding stale data that makes a test look like
  it passed for the wrong reason.
