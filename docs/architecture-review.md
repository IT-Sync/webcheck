# Architecture Review

## Scope

This review covers the central Telegram bot, PostgreSQL access layer, scheduler,
administrative console, remote-agent protocol, and the Telegram Mini App added in
the same process. The main deployment constraint is an in-place update for a live
service with existing customer data.

## Compatibility Strategy

The Mini App is an additive feature:

- it reuses the existing `sites.user_id` Telegram identity and does not migrate or
  rewrite customer records;
- it adds `/app/` and `/api/webapp/*` routes without changing `/admin/*` or the
  WebSocket agent endpoint;
- existing bot commands and callback payloads remain unchanged;
- no destructive or mandatory schema migration is introduced;
- the current Docker service names, volumes, and entry points remain stable.

The Mini App authenticates every API request using signed Telegram `initData`.
Site mutations always include both the site ID and the authenticated Telegram user
ID, preventing cross-account access. New targets reject private, loopback,
link-local, and otherwise non-public resolved addresses.

The current UI also preserves operational compatibility: it derives all metrics
and filters from the existing site payload, sorts problematic resources first
without changing database order, and uses a per-user session cache only as a
temporary first paint before refreshing authoritative data.

## Current Strengths

- Monitoring, Telegram UI, infrastructure, formatting, and remote-agent concerns
  already have recognizable package boundaries.
- Startup schema changes are additive and use `IF NOT EXISTS`.
- PostgreSQL data lives in a bind-mounted `pgdata/` directory and survives image
  rebuilds.
- Remote agents initiate outbound authenticated WebSocket connections, which is a
  practical model for agents behind NAT.
- Compatibility wrapper modules preserve older imports during the ongoing package
  reorganization.

## Risks and Recommended Follow-up

### 1. Global synchronous database connection and cursor — high

`bot.infra.db` creates one process-wide psycopg2 connection and cursor during
module import. Telegram handlers, scheduled checks, the admin console, agent
result handling, and Mini App requests all share them. This blocks the event loop
for database work and makes overlapping cursor operations unsafe.

Recommended follow-up: introduce a repository layer backed by a connection pool,
then migrate call sites incrementally. Keep function signatures stable during the
transition and add integration tests against PostgreSQL before changing the
driver.

### 2. Configuration is read during imports — medium

Several modules read environment variables at import time. In `bot/main.py`,
`.env` is now loaded before application modules to keep local startup consistent
with Docker. Directly importing application modules from other entry points can
still bypass that initialization, and import-time settings are difficult to test
or override.

Recommended follow-up: load environment variables before application imports or
introduce one validated settings object that is passed into application factories.

### 3. Hand-written startup migrations — medium

The current migration function is additive, which is safe for in-place upgrades,
but it has no schema version or migration history. As the schema grows, partial
deployments and rollback reasoning become difficult.

Recommended follow-up: adopt versioned forward-only migrations. Baseline the
existing production schema first; do not recreate or rename existing columns in a
single deployment.

### 4. Monolithic modules and duplicated behavior — medium

The database module, Telegram handlers, scheduler, and admin server are large.
Network-check behavior is duplicated between the central application and remote
agent. This increases the chance of inconsistent fixes.

Recommended follow-up: extract service functions behind existing public imports.
Do not combine this refactor with schema or protocol changes.

### 5. Limited test coverage — medium

Current tests focus on formatters, URL normalization, callback payloads, and Mini
App security helpers. There are no automated PostgreSQL, aiohttp route, scheduler,
or WebSocket protocol integration tests.

Recommended follow-up: add a disposable PostgreSQL test service and aiohttp tests,
then cover ownership checks, notification deduplication, agent timeouts, and
startup against both the old and latest schema.

### 6. Admin session and request protection — medium

The admin console stores the long-lived admin token directly in a cookie and its
mutating forms do not include CSRF tokens. The Mini App does not use this mechanism
and is not affected.

Recommended follow-up: replace the raw token cookie with a short-lived signed
session, set `Secure`, and add CSRF protection. Preserve the existing login route
during one release to avoid locking out operators.

### 7. Blocking and external checks — medium

The central DNS lookup and SSL socket check now run through `asyncio.to_thread`,
so scheduled checks no longer block Mini App responses while waiting for those
operations. PostgreSQL and some auxiliary lookup paths remain synchronous, and a
slow dependency can still delay unrelated bot and web requests.

Recommended follow-up: isolate blocking calls in bounded executors, apply explicit
timeouts, and add per-provider concurrency limits. The Mini App already limits
manual checks to one active check per site in each process.

### 8. Per-process locks and caches — low

Manual-check locks live in process memory, and the Mini App cache lives in the
current Telegram web view's `sessionStorage`. This is appropriate for the current
single application process, but it does not coordinate duplicate manual checks
across multiple replicas. The cache is never treated as authoritative and is
replaced after every successful bootstrap request.

Recommended follow-up: if the service is scaled horizontally, move manual-check
deduplication to PostgreSQL or a distributed lock with a short lease. Keep the
frontend cache session-scoped and avoid storing Telegram authorization data in
persistent browser storage.

## Safe Rollout

1. Back up PostgreSQL with `pg_dump` and retain the existing image tag.
2. Add the new environment variables while keeping the existing database and
   `pgdata/` volume unchanged.
3. Deploy only the rebuilt application container and verify `/admin/`, `/app/`,
   bot polling, and the agent health endpoint. Keep the database container and
   `pgdata/` directory in place.
4. Configure an HTTPS reverse proxy to the shared HTTP listener on port `11003`
   and the WebSocket listener on the fixed port `11001`, then set `WEB_APP_URL`
   to the public `/app/` URL.
5. Test with one Telegram account: open the menu button, confirm that existing
   sites load and problematic resources sort first, use the metric filters, add a
   temporary site, close and reopen the dialog, pause/resume it, run a manual
   check, and delete it.
6. Monitor bot, PostgreSQL, and reverse-proxy logs before rolling the image to all
   hosts.

Rollback only requires restoring the previous application image. This change does
not alter the schema, so no database rollback is needed.
