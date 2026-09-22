# TODO

Last updated: 2026-09-22

This file tracks unresolved work and technical debt. Completed work should be
removed or moved into the current-state sections of `PROJECT_MEMORY.md`; it
should not become a chronological changelog.

## High Priority

- Implement configurable PostgreSQL retention and scheduled cleanup. The current
  `events`, `user_logs`, `bot_messages`, and `agent_check_results` tables retain
  rows indefinitely, while `agent_check_results` may grow by one row per site,
  online agent, and monitoring cycle. The implementation should:
  - define separate retention settings with safe production defaults, initially
    30 days for agent results, 90 days for user and bot logs, and 365 days for
    incident events;
  - never delete active `sites` rows or their current status and incident state;
  - delete old rows in bounded batches using indexed `created_at` predicates so
    cleanup does not hold long locks or delay monitoring;
  - run on a configurable low-frequency schedule, prevent overlapping cleanup
    jobs, and isolate failures from bot polling and monitoring;
  - report deleted-row counts, duration, and failures in application logs;
  - document that normal `VACUUM` makes deleted space reusable but does not
    immediately reduce the database files on disk;
  - include PostgreSQL integration tests for retention boundaries, batching,
    disabled cleanup, empty tables, and rollback after an error;
  - update `.env.example`, `README.md`, `PROJECT_MEMORY.md`, and
    `ARCHITECTURE.md` when implemented, with a backup and rollout procedure for
    the first production cleanup.
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
