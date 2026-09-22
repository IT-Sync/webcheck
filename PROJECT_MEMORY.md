# Project Memory

Last updated: 2026-09-22

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
- PostgreSQL persistence through a synchronous psycopg2 access layer.

## Telegram Mini App

The Mini App is implemented with vanilla HTML, CSS, and JavaScript plus the
Telegram Web App SDK. It has no Node.js toolchain or frontend framework.

Current behavior:

- reads and manages the same sites as the Telegram bot;
- validates signed Telegram `initData` on every API request;
- verifies site ownership for every mutation;
- supports add, delete, pause, resume, and manual check operations;
- provides status-counter filters, domain/group search, group filtering, and
  problem-first, name, or recent sorting;
- supports optional resource groups and a seven-day history view backed by raw
  and hourly aggregated agent results plus relevant monitoring events;
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

The Mini App includes a feedback action that creates a persisted pending session,
sends an instruction message to the user's Telegram chat, and closes the Mini
App. The next non-command text message is stored and not interpreted as a site.
The bot notifies `BOT_OWNER_ID`, while `/admin/feedback` provides an unread
inbox, complete conversation history, and replies delivered from the bot.

## Data Retention

The application includes an opt-in hourly maintenance job. It archives expired
`agent_check_results` into `agent_check_hourly` and deletes raw rows in bounded,
transactional batches using a dedicated database connection. Default retention
is seven days for raw agent results, 90 days for user and bot logs, and 365 days
for events. The interval is configurable and completion logs include deleted
row counts and duration. `DB_MAINTENANCE_ENABLED` defaults to `0`; production
must back up the database, deploy the additive schema, and then enable cleanup
deliberately. Maintenance verifies that the operator-created cleanup index is
both ready and valid; failed concurrent builds can leave an invalid index that
must be dropped and rebuilt concurrently.

The administrative console uses the same dark control-room visual language as
the Mini App. Its dedicated `/admin/sites` registry lists every customer's
resource in problem-first order and supports immediate search by domain,
username, Telegram user ID, or group plus status filtering and direct owner
navigation. Other administrative tables retain page-level search.

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

The product backlog in `TODO.md` covers longer-period charts, tags, maintenance
windows, regional comparisons, monitoring health, incident
confirmation and acknowledgement, notification preferences, bulk operations,
public status pages, content/API checks, DNS changes, and team access. These
features are not yet implemented. The proposed sequence starts with retention
and aggregation before history, groups, maintenance, and public status pages.

## Validation Baseline

The current suite contains 44 passing `unittest` tests. Standard validation is:

```bash
python -m unittest discover -s tests -v
python -m compileall -q bot agent tests
git diff --check
```

## Authoritative References

- `ARCHITECTURE.md` — runtime topology, boundaries, routes, data flow, and agent
  protocol.
- `TODO.md` — unresolved engineering work and known limitations.
- `README.md` — operator setup, Nginx configuration, rollout, and verification.
- `docs/architecture-review.md` — detailed risk assessment and rollout guidance.
