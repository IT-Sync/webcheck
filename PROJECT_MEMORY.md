# Project Memory

Last updated: 2026-09-24

## Current State

Webcheck is a production Telegram website-monitoring service used by existing
customers. Changes must support in-place deployment and preserve PostgreSQL
data, bot behavior, public routes, and compatibility with deployed agents.

The central Python 3.11 process currently provides:

- aiogram Telegram bot commands, callbacks, alerts, and reports;
- APScheduler-based background monitoring;
- an aiohttp administrative console;
- a Telegram Mini App and authenticated JSON API;
- a WebSocket server for remote checking agents;
- PostgreSQL persistence through a synchronous repository layer backed by a
  thread-safe psycopg2 connection pool.

## Telegram Mini App

The Mini App is implemented with vanilla HTML, CSS, and JavaScript plus the
Telegram Web App SDK. It has no Node.js toolchain or frontend framework.

Current behavior:

- reads and manages the same sites as the Telegram bot;
- validates signed Telegram `initData` on every API request;
- verifies site ownership for every mutation;
- supports add, delete, pause, resume, and manual check operations;
- provides status-counter filters, domain/group/tag search, independent group
  and tag filtering, and problem-first, name, or recent sorting;
- supports optional resource groups, up to eight tags per resource, and
  selectable one-day, seven-day, and 30-day history views; the authenticated
  API accepts periods from one to 90
  days, uses hourly buckets through seven days and daily buckets after that,
  and combines raw, hourly, and daily agent aggregates with monitoring events
  and durable central incidents;
- shows availability, average and peak latency, and availability grouped by
  remote agent and region;
- renders session-cached site data immediately and refreshes it from the server;
- supports closing the add dialog through its close control, Telegram Back,
  Escape, and backdrop interaction where the web view supports it;
- shows a dedicated branded access page instead of the monitoring dashboard when
  `/app/` is opened without signed Telegram `initData`, and performs no API
  requests in that mode;
- validates new domains with a bounded DNS lookup and rejects non-public IPs;
- moves blocking central DNS and TLS socket work outside the asyncio event loop.

Static asset URLs are versioned, and the Mini App shell is served with no-cache
headers to reduce stale Telegram web-view assets after deployment.

## Monitoring and Incident Controls

HTTP outage alerts use a configurable consecutive-failure threshold and an
optional central confirmation request. Remote-agent results are then appended
to the alert for context, but they do not currently decide whether the global
outage alert is sent. Incident alert actions support an immediate check, history
view, and a one-hour maintenance window. Users can also schedule arbitrary future
maintenance windows with explicit start/end times and reasons, cancel active or
future windows, and retain completed intervals for history and reports.

Each continuous centrally detected outage is stored as a structured incident
with start and recovery diagnostics and the failure count observed when the
incident opened. The legacy current-incident fields on `sites` remain for
runtime compatibility, while `central_incidents` provides durable intervals for
history. Central incidents are displayed separately from remote-agent
availability because the service does not yet retain every successful central
check needed to calculate central availability.

The admin console shows currently connected agents with their connection,
heartbeat, and last-result timestamps. Agent state is process-local and is not
yet retained or converted into disconnect, overdue-check, or central-watchdog
alerts.

The Mini App includes a feedback action that creates a persisted pending session,
sends an instruction message to the user's Telegram chat, and closes the Mini
App. The next non-command message is stored rather than interpreted as a site
and may contain text, a caption, photos, video,
documents, audio, voice, video notes, or a Telegram media group. Attachments are
stored as Telegram file identifiers rather than database blobs. The bot notifies
`BOT_OWNER_ID`, while `/admin/feedback` provides an unread inbox, protected
attachment viewing, complete conversation history, and replies delivered from
the bot.

## Database Access

`bot.infra.repository.DatabaseRepository` owns a bounded, thread-safe psycopg2
connection pool. Existing functions in `bot.infra.db` retain their signatures
through compatibility cursor and connection facades while each worker thread
checks out an independent connection. Reads release their connection after
fetching; writes retain it until commit or rollback. `DB_POOL_MIN_SIZE` defaults
to one and `DB_POOL_MAX_SIZE` to ten. The access layer remains synchronous, so
database calls made directly from async handlers can still block the event loop.

Disposable PostgreSQL integration tests cover commit, rollback, and concurrent
pool use when `TEST_DATABASE_URL` is set.

## Data Retention

The application includes an opt-in hourly maintenance job. It archives expired
`agent_check_results` into `agent_check_hourly`, then archives expired hourly
rows into `agent_check_daily`; both stages delete their source rows in bounded,
transactional batches using a dedicated database connection. Default retention
is seven days for raw agent results, 30 days for hourly aggregates, 90 days for
user and bot logs, and 365 days for events. The interval and hourly retention
are configurable, and completion logs include archived row counts and duration.
`DB_MAINTENANCE_ENABLED` defaults to `0`; production must back up the database,
deploy the additive schema, and then enable cleanup deliberately. Maintenance
verifies that the operator-created cleanup index is both ready and valid;
failed concurrent builds can leave an invalid index that must be dropped and
rebuilt concurrently.

Availability is calculated only from observed remote-agent checks. Missing
checks are excluded from the denominator rather than treated as success or
failure. Manual pauses and active maintenance windows suppress scheduled central
and remote-agent checks, so their absent samples are excluded. Manual checks remain available during maintenance for diagnostics; any agent
results they produce remain observed samples and are included in availability.
Maintenance intervals are shown separately from central incidents in history and weekly reports.

The administrative console uses the same dark control-room visual language as
the Mini App. Its dedicated `/admin/sites` registry lists every customer's
resource in problem-first order and supports immediate search by domain,
username, Telegram user ID, group, or tag plus status filtering and direct owner
navigation. Other administrative tables retain page-level search. Every
non-empty data-table column can be sorted in either direction by mouse or
keyboard, with type-aware ordering for numbers, timestamps, and text.

## Production Deployment

- Application repository path used by operators: `/opt/pybot/webcheck`.
- Shared admin/Mini App HTTP listener: `ADMIN_WEB_PORT=11003`.
- Remote-agent WebSocket listener: `AGENT_WS_PORT=11001`; this port must not be
  changed.
- Nginx runs on a separate host and proxies to the application server's private
  address.
- Port `11003` must therefore be published on an address reachable from Nginx,
  not only on `127.0.0.1`.
- Public Mini App traffic uses `/app/` and `/api/webapp/*` over HTTPS.
- Public agent traffic uses `/ws/agents` over WSS and is proxied to port `11001`.
- PostgreSQL data is stored in the bind-mounted `./pgdata` directory.

Safe application updates rebuild and replace only `devcheck-bot`. They must not
remove `pgdata`, run `docker compose down -v`, or introduce destructive startup
migrations. Back up PostgreSQL before major releases.

## Compatibility Constraints

- Keep Python 3.11 compatibility.
- Preserve bot callback payloads and compatibility-wrapper imports.
- Keep database migrations additive and idempotent.
- Keep the remote-agent message protocol backward compatible.
- Do not change Docker Compose service names, ports, routes, or environment
  variable names without an explicit migration plan.
- Continue responding to the user in Russian while repository-facing text stays
  in English.

## Planned Development

The product backlog in `TODO.md` covers automatic global-versus-regional
classification, monitoring-health alerts, multi-agent incident confirmation,
acknowledgement, notification preferences, bulk operations, public status pages,
content/API checks, DNS changes, and team access. Some foundations exist as
documented above, but these extensions are not yet implemented. The proposed
next sequence is regional classification and public status pages.

## Validation Baseline

The current suite contains 62 `unittest` tests. The standard run passes 57 and
skips five PostgreSQL integration tests unless `TEST_DATABASE_URL` points to a
disposable database; all 62 pass when that database is provided.

```bash
python -m unittest discover -s tests -v
TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/webcheck_test \
  python -m unittest -v tests.test_repository_postgres
python -m compileall -q bot agent tests
git diff --check
```

## Authoritative References

- `ARCHITECTURE.md` — runtime topology, boundaries, routes, data flow, and agent
  protocol.
- `TODO.md` — unresolved engineering work and known limitations.
- `README.md` — operator setup, Nginx configuration, rollout, and verification.
- `docs/architecture-review.md` — detailed risk assessment and rollout guidance.
