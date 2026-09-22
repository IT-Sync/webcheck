# Architecture

## Runtime Topology

One central Python process runs four cooperating surfaces:

1. aiogram long polling for Telegram bot commands and callbacks;
2. APScheduler jobs for periodic monitoring and reports;
3. one aiohttp server for the admin console and Telegram Mini App;
4. a separate aiohttp WebSocket server for remote checking agents.

PostgreSQL stores users' monitored sites, status text, incident state, events,
and audit records. The standalone application under `agent/` has no inbound
public API; it opens an authenticated WebSocket connection to the central
service.

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

## Module Responsibilities

- `bot/main.py` loads `.env`, creates the bot, configures the Telegram Mini App
  menu button, starts the scheduler and both web servers, and begins polling.
- `bot/telegram/` owns bot commands, callbacks, scheduler integration, message
  tracking, and notification delivery.
- `bot/webapp/` owns Telegram `initData` validation, public-target validation,
  Mini App API routes, and static assets.
- `bot/admin_console/` owns the administrative UI and hosts the shared aiohttp
  application used by `/admin/`, `/app/`, and `/api/webapp/`.
- `bot/agent_server/` owns WebSocket authentication, the online-agent registry,
  check dispatch, and result correlation.
- `bot/checks/` owns central HTTP, TLS, WHOIS, GeoIP, and subdomain checks.
- `bot/checks/service.py` provides the shared resource-check service used by UI
  and scheduler flows.
- `bot/infra/db.py` owns the synchronous PostgreSQL access layer, schema setup,
  and additive startup migrations.
- `bot/core/` contains URL helpers and formatters that do not depend on Telegram
  or PostgreSQL.
- `agent/` is a separately deployable remote checker.

Top-level modules such as `bot/monitor.py` and `bot/db.py` are compatibility
wrappers. They preserve existing imports while implementation moves into the
packages above.

## Telegram Mini App Request Flow

1. Telegram opens `WEB_APP_URL` and injects signed `initData` through the Web App
   SDK.
2. The frontend sends it in `Authorization: tma <initData>` on every API request.
3. `bot.webapp.auth` verifies the HMAC-SHA256 signature and `auth_date` using the
   bot token.
4. API handlers use only the verified Telegram user ID for reads and mutations.
5. Existing site rows are serialized into status kinds: `up`, `down`, `warning`,
   `pending`, or `paused`.

The frontend immediately renders a per-user `sessionStorage` snapshot when
available, then refreshes `/api/webapp/bootstrap`. Metrics act as status filters,
and the default client-side sort places problematic resources first.

Before inserting a site, the server normalizes the URL, resolves its hostname
with a bounded timeout, and rejects any non-global address. A full monitoring
check is deliberately not part of insertion. DNS and TLS socket work is moved to
worker threads so it cannot block the aiohttp/aiogram event loop.

Manual checks are serialized per site within the process. They run the central
check and collect online-agent results before updating the stored status.

## Web Routes

| Listener | Route | Authentication | Purpose |
| --- | --- | --- | --- |
| `11003` | `/app/` | Telegram supplies auth to API | Mini App static shell |
| `11003` | `/api/webapp/bootstrap` | Telegram `initData` | User, metrics, and sites |
| `11003` | `/api/webapp/sites` | Telegram `initData` | Add a site |
| `11003` | `/api/webapp/sites/{id}/*` | Telegram `initData` + ownership | Check or mutate a site |
| `11003` | `/admin/*` | Admin token cookie/query | Operator console |
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

## Data and Upgrade Compatibility

The Mini App reuses the existing `sites.user_id` Telegram identity and does not
add a second account model. Startup schema operations are additive and
idempotent. The PostgreSQL data directory is bind-mounted at `./pgdata`, so an
application image rebuild does not replace customer data.

The primary architectural constraint is the process-wide synchronous psycopg2
connection and cursor. Database calls can block the event loop and concurrent
cursor use is unsafe. A future repository/pool migration should preserve public
function signatures and be rolled out separately from schema or protocol
changes. See `architecture-review.md` for the full risk assessment.
