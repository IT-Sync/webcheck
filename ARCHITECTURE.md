# Architecture

## Runtime Topology

One central Python process runs four cooperating surfaces:

1. aiogram long polling for Telegram bot commands and callbacks;
2. APScheduler jobs for periodic monitoring and reports;
3. one aiohttp server for the admin console and Telegram Mini App;
4. a separate aiohttp WebSocket server for remote checking agents.

PostgreSQL stores monitored sites, status text, incident state, events, and audit
records. The standalone application under `agent/` has no inbound public API; it
opens an authenticated WebSocket connection to the central service.

```text
Telegram client
  |-- bot updates --------------------------> aiogram
  `-- HTTPS /app/ and /api/webapp/* -> Nginx -> aiohttp :11003
                                                |
Operator -- HTTPS /admin/ ------------> Nginx -+
                                                |
Remote agents -- WSS /ws/agents ------> Nginx -> agent server :11001
                                                |
                                  services/checks/scheduler
                                                |
                                           PostgreSQL
```

Production keeps `AGENT_WS_PORT=11001`. The shared admin/Mini App listener uses
`ADMIN_WEB_PORT=11003`. Nginx may run on another host, so these ports must be
published on a private address reachable from Nginx and protected by a firewall.

## Component Boundaries

- `bot/main.py` loads `.env`, creates the bot, configures the Telegram Mini App
  menu button, starts the scheduler and both web servers, and begins polling.
- `bot/telegram/` owns bot commands, callbacks, scheduler integration, message
  tracking, and notification delivery. Owner-only commands live in
  `admin_commands.py`; scheduled report delivery and blocked-user cleanup live
  in `reporting.py`. `handlers.py` and `scheduler.py` retain their public imports
  and registration entry points.
- `bot/webapp/` owns Telegram `initData` validation, public-target validation,
  Mini App API routes, and static assets.
- `bot/admin_console/` owns the administrative UI and hosts the shared aiohttp
  application used by `/admin/`, `/app/`, and `/api/webapp/`. Its shared page
  shell, navigation, styling, and client-side table behavior live in
  `layout.py`; `server.py` owns routes and request handling.
- `bot/agent_server/` owns WebSocket authentication, the online-agent registry,
  check dispatch, and result correlation.
- `bot/checks/` owns central HTTP, TLS, WHOIS, GeoIP, and subdomain checks.
- `bot/checks/service.py` provides the shared resource-check service used by UI
  and scheduler flows.
- `bot/infra/repository.py` owns the bounded, thread-safe psycopg2 connection
  pool and explicit transaction context.
- `bot/infra/db.py` retains the public persistence function signatures and
  additive startup migrations while routing compatibility cursor/connection
  operations through the repository. `bot/infra/schema.py` creates the base
  tables in the existing order and transaction at import time.
- `bot/core/` contains URL helpers and formatters that do not depend on Telegram
  or PostgreSQL.
- `agent/` is a separately deployable remote checker.

Top-level modules such as `bot/monitor.py` and `bot/db.py` are compatibility
wrappers. They preserve existing imports while implementation moves into the
packages above.

## Telegram Mini App Data Flow

1. Telegram opens `WEB_APP_URL` and injects signed `initData` through the Web App
   SDK.
2. The frontend sends it in `Authorization: tma <initData>` on every API request.
3. `bot.webapp.auth` verifies the HMAC-SHA256 signature and `auth_date` using the
   bot token.
4. API handlers use only the verified Telegram user ID for reads and mutations.
5. Existing site rows are serialized into status kinds: `up`, `down`, `warning`,
   `pending`, or `paused`.

When `/app/` is opened outside Telegram, the static shell detects the absence of
`initData`, displays a dedicated access page, and stops before registering the
dashboard or making API requests. The monitoring dashboard remains hidden by
default and is revealed only for a Telegram-authenticated launch. Server-side
API authentication remains authoritative; the client-side gate is a presentation
and request-avoidance measure, not an authorization boundary.

The frontend immediately renders a per-user `sessionStorage` snapshot when
available, then refreshes `/api/webapp/bootstrap`. Metrics act as status filters,
and the default client-side sort places problematic resources first. The cache
is a display optimization and is never authoritative.

Sites belong to `projects`, each with an explicit owner; `project_members`
stores `viewer` and `manager` roles. The additive startup migration backfills
existing sites into each owner's personal project. `sites.user_id` remains the
owner and alert recipient for compatibility with scheduling and Telegram bot
commands. The Mini App lists accessible projects and filters resources by project.
Viewers can read status and history; managers can mutate sites; only owners can
manage project members. Database writes enforce these permissions independently
of UI controls. The owner cannot be removed while a project has members.

Sites have an optional `site_group` field and normalized rows in `site_tags`.
Search plus independent group and tag filtering happen in the Mini App over the
authenticated user's bootstrap payload. The history endpoint verifies project
access before combining relevant `events`, retained raw agent results,
`agent_check_hourly` and `agent_check_daily` aggregates, and structured central
incidents. Requests through seven days use hourly buckets; longer requests use
daily buckets, up to the 90-day API limit. The UI exposes one-day, seven-day,
and 30-day selections and renders availability plus average and peak latency.
Availability uses observed remote-agent checks only: missing checks and checks
omitted during a manual pause or active maintenance window are excluded from the
denominator. Agent results from an explicit manual check remain observed samples
and are included. `maintenance_windows` records start/end times, reasons,
cancellation, and completed intervals separately from incidents.

Before inserting a site, the server normalizes the URL, resolves its hostname
with a bounded timeout, and rejects any non-global address. A full monitoring
check is deliberately not part of insertion. DNS and TLS socket work runs in
worker threads so it cannot block the aiohttp/aiogram event loop.

Manual checks are serialized per site within the process. They remain available
during maintenance for diagnostics, run the central check, and collect
online-agent results before updating the stored status. Scheduled monitoring
queries exclude manual pauses and currently active maintenance windows; future
windows start and completed windows expire automatically through time predicates.
Each continuous central outage creates or updates one `central_incidents` row;
recovery closes that interval with recovery diagnostics. These intervals are
shown alongside, but are not folded into, remote-agent availability because
successful central checks are not retained as a complete time series.

Feedback starts through the authenticated Mini App API or `/feedback`. A
persisted `feedback_conversations.waiting_for_user` flag routes the next
non-command text or supported media message into `feedback_messages` instead of
the site-input handler. Captions and Telegram file metadata are retained, while
album items continue to match through `active_media_group_id`. The bot notifies
`BOT_OWNER_ID` and copies attachments into the owner chat. Authenticated
operators read the thread and reply through the admin console, which sends the
response through the same bot before recording it as an administrator message.

## Web Routes

| Listener | Route | Authentication | Purpose |
| --- | --- | --- | --- |
| `11003` | `/app/` | Telegram supplies auth to API | Mini App static shell |
| `11003` | `/api/webapp/bootstrap` | Telegram `initData` | User, metrics, and sites |
| `11003` | `/api/webapp/sites` | Telegram `initData` | Add a site |
| `11003` | `/api/webapp/sites/{id}/*` | Telegram `initData` + ownership | Check or mutate a site |
| `11003` | `/api/webapp/sites/{id}/history` | Telegram `initData` + ownership | Resource history and aggregates |
| `11003` | `/api/webapp/sites/{id}/tags` | Telegram `initData` + ownership | Replace resource tags |
| `11003` | `/api/webapp/sites/{id}/maintenance/*` | Telegram `initData` + ownership | Schedule, list, or cancel maintenance |
| `11003` | `/api/webapp/feedback/start` | Telegram `initData` | Start a persisted bot feedback session |
| `11003` | `/admin/*` | Admin token cookie/query | Operator console |
| `11003` | `/admin/sites` | Admin token cookie/query | Searchable cross-user resource registry |
| `11003` | `/admin/feedback/*` | Admin token cookie/query | Feedback inbox, threads, and replies |
| `11003` | `/admin/feedback/media/{id}` | Admin token cookie/query | Telegram attachment proxy |
| `11001` | `/health` | None | Agent server health probe |
| `11001` | `/ws/agents` | Token in `agent.hello` | Remote-agent WebSocket |

## Remote-agent Protocol

The agent initiates the connection, which supports deployments behind NAT and
firewalls. Its first message authenticates and describes the location:

```json
{
  "type": "agent.hello",
  "agent_id": "server-a",
  "country": "RU",
  "region": "Moscow",
  "provider": "",
  "token": "shared-agent-secret"
}
```

The server acknowledges the connection and can send a job:

```json
{
  "type": "check.request",
  "job_id": "uuid",
  "url": "https://example.com",
  "checks": ["http", "ssl", "domain"],
  "timeout_sec": 30
}
```

The agent returns a correlated result:

```json
{
  "type": "check.result",
  "job_id": "uuid",
  "agent_id": "server-a",
  "country": "RU",
  "region": "Moscow",
  "ok": true,
  "http": {
    "ok": true,
    "status_code": 200,
    "latency_ms": 120,
    "ip": "203.0.113.10"
  },
  "ssl_days": 42,
  "domain_days": 180,
  "registrar": "Example Registrar",
  "contact_url": null,
  "error": null
}
```

Agents also send `agent.ping`; the server replies with `server.pong`. Protocol
extensions must remain backward compatible because agents may be upgraded after
the central service.

## Persistence and Upgrades

The Mini App reuses the existing `sites.user_id` Telegram identity and does not
add a second account model. Startup schema operations are additive and
idempotent. The PostgreSQL data directory is bind-mounted at `./pgdata`, so an
application image rebuild does not replace customer data.

`feedback_conversations` stores one durable thread per Telegram user, including
whether the bot is waiting for the next message. `feedback_messages` stores the
user/admin transcript, unread state, captions, and Telegram file identifiers.
Binary files remain in Telegram rather than PostgreSQL. The admin media route
downloads them server-side without exposing the bot token, restricts inline
content types, and forces other files to download. Deleting all data for a user
cascades to the feedback transcript; ordinary site deletion does not affect
feedback.

`agent_check_results` contains short-lived raw results. The hourly maintenance
job selects expired rows in bounded batches, aggregates them first into
`agent_check_hourly` and later into `agent_check_daily`, and deletes each
selected source batch in the same transaction. The daily table preserves check
counts, successes, failures, latency sums and samples, and peak latency for
longer history views. The job uses its own PostgreSQL connection and runs
through `asyncio.to_thread` so maintenance does not consume application pool
capacity or block the event loop. Retention is opt-in through
`DB_MAINTENANCE_ENABLED`; the maintenance interval is configurable and current
defaults keep seven days of raw agent results, 30 days of hourly aggregates, 90
days of user and bot logs, and 365 days of events. Cleanup requires an
operator-created concurrent index on raw result
timestamps; the application deliberately avoids building that large index in a
startup transaction. The guard checks PostgreSQL's `indisready` and `indisvalid`
flags because an interrupted concurrent build may leave an unusable catalog
entry with the expected index name.

`central_incidents` stores one durable row per continuous centrally detected
outage, including start and recovery diagnostics. A partial unique index permits
only one open incident per site. The current incident fields on `sites` remain
as compatibility state for existing scheduler and notification behavior.

`site_tags` stores multiple labels per resource with cascade deletion.
`maintenance_windows` stores scheduled, active, completed, and cancelled planned
intervals. Overlapping non-cancelled windows for one resource are rejected by the
repository transaction. Weekly reports include windows overlapping the previous
seven days and distinguish currently active maintenance from manual pauses.

The central application uses a bounded `ThreadedConnectionPool`. Legacy
`bot.infra.db` functions and signatures are preserved by compatibility
connection/cursor facades; each worker thread checks out its own connection,
read transactions are released after fetch, and write transactions retain the
same connection through commit or rollback. Pool exhaustion waits for a returned
connection rather than sharing a cursor. The database API is still synchronous,
so calls made directly from async handlers can block the event loop; moving
those calls off-loop remains a separate incremental migration.

## Architecture Maintenance

Update this file in the same change whenever component boundaries, APIs, data
flow, storage, authentication, external integrations, networking, ports,
runtime topology, deployment, background processing, caches, or CI/CD change.
If this document conflicts with implementation, verify the code and correct this
document immediately.
