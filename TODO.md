# TODO

Last updated: 2026-09-22

This file tracks unresolved work and technical debt. Completed work should be
removed or moved into the current-state sections of `PROJECT_MEMORY.md`; it
should not become a chronological changelog.

## High Priority

- Replace the process-wide synchronous psycopg2 connection and cursor with a
  repository layer backed by a connection pool. Preserve current public
  function signatures during incremental migration and add PostgreSQL
  integration tests first.

## Medium Priority

- Introduce one validated settings object instead of reading environment
  variables across module imports.
- Adopt versioned, forward-only database migrations after baselining the current
  production schema. Do not combine this with destructive schema changes.
- Replace the raw admin-token cookie with a short-lived signed session, set
  secure cookie attributes, and add CSRF protection while retaining a compatible
  operator login path for one release.
- Add disposable PostgreSQL and aiohttp integration tests covering Mini App
  ownership checks, startup against old and current schemas, scheduler behavior,
  notification deduplication, and WebSocket-agent timeouts.
- Continue separating large Telegram, scheduler, admin, and database modules
  behind existing compatibility imports.
- Apply explicit timeouts and bounded concurrency to remaining synchronous or
  external lookup paths.

## Scaling Limitations

- Mini App manual-check locks are process-local. Before running multiple central
  application replicas, move deduplication to PostgreSQL or a distributed lock
  with a short lease.
- The remote-agent registry is process-local and assumes one central agent
  server instance.
- Network-check behavior exists in both `bot/checks/` and `agent/checks.py` and
  must be kept deliberately synchronized until a shared contract or test suite
  is introduced.
