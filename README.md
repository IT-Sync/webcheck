# Webcheck

Webcheck is a Telegram-first website monitoring service. It checks HTTP
availability, TLS certificate lifetime, domain registration lifetime, and
GeoIP data. Users can manage the same monitored resources from the Telegram bot
or the Telegram Mini App. Operators have a separate administrative console, and
remote agents can run checks from other networks or regions.

The service is designed for in-place upgrades: existing PostgreSQL data is kept,
schema changes are additive, and the current bot commands and agent protocol
remain compatible.

## Features

- Scheduled HTTP, TLS, WHOIS, and GeoIP checks with Telegram alerts.
- Consecutive-failure thresholds and a confirming check before a DOWN alert.
- Telegram commands and inline controls for adding, checking, pausing, resuming,
  and deleting resources.
- Telegram Mini App with the current resource status, manual checks, resource
  management, status filters, and problem-first sorting.
- Fast Mini App startup from a session cache while current data loads in the
  background.
- Resource groups, search, group filtering, and a seven-day history view with
  regional availability, response-time summaries, and monitoring events.
- Bounded DNS validation when a site is added, including rejection of private,
  loopback, link-local, and other non-public targets.
- Administrative console with sortable data tables, a searchable all-site
  registry, direct owner navigation, a feedback inbox with bot replies, and
  user, event, message, and agent management.
- Authenticated outbound WebSocket agents for checks from remote locations.
- CSV exports for logs, sites, and subdomain discovery results.

## Technology

- Python 3.11, asyncio, aiogram 3, aiohttp, and APScheduler.
- PostgreSQL 15 through psycopg2.
- Vanilla HTML, CSS, and JavaScript with the Telegram Web App SDK. The Mini App
  has no Node.js build step or frontend framework.
- aiohttp, cryptography, python-whois, ipwhois, and BeautifulSoup for checks and
  enrichment.
- Docker Compose for deployment and Nginx with TLS for public access.
- Standard-library `unittest` tests.

## Repository Layout

```text
bot/
  main.py              Central application entry point
  telegram/            Bot handlers, callbacks, scheduler, and notifications
  webapp/              Telegram Mini App API, authentication, validation, assets
  admin_console/       Operator web console and shared aiohttp server
  agent_server/        WebSocket server and connected-agent registry
  checks/              HTTP, TLS, WHOIS, GeoIP, and subdomain checks
  infra/               PostgreSQL access and additive startup migrations
  core/                Formatting and URL helpers
agent/                  Standalone remote checking agent
docs/                   Architecture and review documentation
tests/                  Unit tests
```

The top-level modules such as `bot/db.py`, `bot/monitor.py`, and
`bot/handlers.py` are compatibility wrappers for older imports.

## Configuration

Copy the example and replace every placeholder secret:

```bash
cp .env.example .env
```

The production port allocation is:

- `11003` — admin console, Mini App, and `/api/webapp/*` over HTTP inside the
  private network;
- `11001` — remote-agent WebSocket server. Keep `AGENT_WS_PORT=11001` unchanged.

The most important settings are shown below. See [.env.example](.env.example)
for the complete list.

```env
BOT_TOKEN=replace_with_botfather_token
BOT_OWNER_ID=123456789

DB_NAME=devcheck
DB_USER=devuser
DB_PASS=replace_with_database_password
DB_HOST=db
DB_PORT=5432

ADMIN_WEB_TOKEN=replace_with_a_long_random_token
ADMIN_WEB_HOST=0.0.0.0
ADMIN_WEB_PORT=11003

WEB_APP_ENABLED=1
WEB_APP_URL=https://webcheck.example.com/app/
WEB_APP_AUTH_MAX_AGE_SECONDS=86400
WEB_APP_MAX_SITES_PER_USER=50
WEB_APP_DNS_TIMEOUT_SECONDS=3
WEB_APP_CHECK_TIMEOUT_SECONDS=10
WEB_APP_AGENT_TIMEOUT_SECONDS=5

DB_MAINTENANCE_ENABLED=0
AGENT_RESULT_RETENTION_DAYS=7
USER_LOG_RETENTION_DAYS=90
BOT_MESSAGE_RETENTION_DAYS=90
EVENT_RETENTION_DAYS=365
DB_CLEANUP_BATCH_SIZE=5000
DB_CLEANUP_MAX_BATCHES=10
DB_MAINTENANCE_INTERVAL_HOURS=1

AGENT_WS_TOKEN=replace_with_a_separate_agent_token
AGENT_WS_HOST=0.0.0.0
AGENT_WS_PORT=11001
AGENT_WS_PATH=/ws/agents
AGENT_WS_PUBLISH_HOST=0.0.0.0
```

`WEB_APP_URL` must be the public HTTPS URL ending in `/app/`. At startup the bot
sets this URL as its Telegram menu button; `/start` and `/app` also provide a
button that opens the Mini App.

Never commit `.env`, Telegram tokens, web tokens, database dumps, or `pgdata/`.

## Start with Docker Compose

```bash
docker compose up -d --build
docker compose logs --tail=150 devcheck-bot
```

Expected startup messages include:

```text
Admin web console started on http://0.0.0.0:11003/admin/
Telegram Mini App started on http://0.0.0.0:11003/app/
Agent WebSocket server started on ws://0.0.0.0:11001/ws/agents
```

Stop containers without removing customer data:

```bash
docker compose down
```

Do not add `-v` and do not delete `./pgdata`.

## Nginx on a Separate Host

When Nginx runs on another server, port `11003` must be bound to a private
address reachable from that server. A `127.0.0.1:11003` Docker publication is
not reachable remotely and results in `502 Bad Gateway`. Restrict access to the
Nginx host with the firewall.

Example configuration for an application host at `10.1.0.4`:

```nginx
upstream webcheck_http {
    server 10.1.0.4:11003;
    keepalive 16;
}

upstream webcheck_agents {
    server 10.1.0.4:11001;
}

server {
    listen 443 ssl;
    server_name webcheck.example.com;

    ssl_certificate /etc/letsencrypt/live/webcheck.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/webcheck.example.com/privkey.pem;

    location / {
        proxy_pass http://webcheck_http;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/agents {
        proxy_pass http://webcheck_agents;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
    }
}
```

Verify connectivity from the Nginx host before reloading Nginx:

```bash
curl -i http://10.1.0.4:11003/app/
curl -i http://10.1.0.4:11001/health
nginx -t
systemctl reload nginx
```

## Telegram Mini App

The Mini App and admin console share one aiohttp listener on port `11003`, but
they use independent authentication:

- `/app/` serves the Mini App frontend;
- `/api/webapp/*` validates signed Telegram `initData` using the bot token;
- `/admin/` requires `ADMIN_WEB_TOKEN`;
- the client never supplies a trusted Telegram user ID directly.

The Mini App reuses existing rows keyed by `sites.user_id`; enabling it requires
no data migration. Mutating API operations verify both the site ID and the
authenticated Telegram user ID. The resource list is cached only in Telegram's
current web view session and is refreshed from the server on every opening.

Opening `/app/` in a regular browser shows a branded Telegram access page rather
than the monitoring dashboard. The frontend does not call the Mini App API until
Telegram provides signed `initData`; server-side signature validation remains
the actual security boundary.

Resource metrics are interactive filters. The default sort order places DOWN,
warning, and pending resources before healthy and paused resources. Users can
also sort by name or most recent check.

Users can assign a resource to a group, search by domain or group, and filter the
list by group. The resource history action shows the last seven days of
availability and response-time aggregates by remote agent together with relevant
monitoring events. Existing sites start with no group and require no data
migration by operators.

Adding a site validates DNS but does not perform a full HTTP/TLS/WHOIS check in
the request path. DNS work has a configurable timeout, and blocking DNS and TLS
operations run outside the asyncio event loop. The first complete result is
produced by the scheduler or by **Check now**.

The **Feedback** button starts a persisted feedback session, sends instructions
to the user's bot chat, and closes the Mini App. The next non-command message is
stored in the conversation and forwarded as a notification to `BOT_OWNER_ID`.
Text, captions, photos, videos, animations, documents, audio, voice messages,
video notes, and multi-item Telegram media groups are supported. Operators can
read the complete thread under `/admin/feedback`, view or download attachments
through an authenticated proxy, and send a reply that is delivered by the bot.
Users can also start the flow with `/feedback` or cancel it with
`/cancel_feedback`.

## Remote Agents

The central WebSocket listener uses port `11001`. Agents initiate outbound
connections, authenticate with `AGENT_WS_TOKEN`, receive check jobs, and return
structured results. Public agents normally connect through:

```env
SERVER_WS_URL=wss://webcheck.example.com/ws/agents
```

Start an agent on a remote host:

```bash
cd agent
cp .env.example .env
docker compose up -d --build
docker compose logs -f webcheck-agent
```

See [agent/README.md](agent/README.md) for its configuration and protocol.

## Database Retention and Aggregation

Raw remote-agent results grow by one row per site, online agent, and monitoring
cycle. The maintenance job archives expired raw results into hourly aggregates
before deleting them. History reads combine retained raw rows with aggregates,
so cleanup does not remove chart history.

Maintenance runs hourly in bounded batches and uses a dedicated PostgreSQL
connection outside the asyncio event loop. It is disabled by default for a safe
first deployment. Recommended production settings are:

```env
DB_MAINTENANCE_ENABLED=1
AGENT_RESULT_RETENTION_DAYS=7
USER_LOG_RETENTION_DAYS=90
BOT_MESSAGE_RETENTION_DAYS=90
EVENT_RETENTION_DAYS=365
DB_CLEANUP_BATCH_SIZE=5000
DB_CLEANUP_MAX_BATCHES=10
DB_MAINTENANCE_INTERVAL_HOURS=1
```

For the first rollout:

1. Back up PostgreSQL.
2. Deploy with `DB_MAINTENANCE_ENABLED=0` and confirm that startup creates
   `agent_check_hourly` and the additive site fields.
3. Create the cleanup index online, without blocking normal writes for the full
   build duration:

   ```bash
   docker compose exec -T db psql -U devuser -d devcheck -c \
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_agent_check_results_created_at ON agent_check_results(created_at);"
   ```

4. Enable maintenance and restart only `devcheck-bot`.
5. Watch for `Database maintenance completed` in application logs and monitor
   the row count of `agent_check_results`.

Each batch archives and deletes rows in one transaction. Cleanup never deletes
the `sites` table. Normal PostgreSQL autovacuum makes deleted space reusable;
database files do not necessarily shrink immediately.

Maintenance refuses to run without `idx_agent_check_results_created_at`. The
large index is deliberately not built during application startup because the
existing production table may contain millions of rows.

If a concurrent build is interrupted by a deadlock or another error, PostgreSQL
can leave an index with the requested name but mark it invalid. Check and recover
it before enabling maintenance:

```bash
docker compose exec -T db psql -U devuser -d devcheck -c \
  "SELECT c.relname, i.indisready, i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid WHERE c.relname = 'idx_agent_check_results_created_at';"

docker compose exec -T db psql -U devuser -d devcheck -c \
  "DROP INDEX CONCURRENTLY IF EXISTS idx_agent_check_results_created_at;"

docker compose exec -T db psql -U devuser -d devcheck -c \
  "CREATE INDEX CONCURRENTLY idx_agent_check_results_created_at ON agent_check_results(created_at);"
```

Run only one concurrent index build on `agent_check_results` at a time. The
maintenance guard checks both `indisready` and `indisvalid`, so an incomplete
index cannot accidentally enable cleanup.

## Safe In-place Update

Back up PostgreSQL before a major release:

```bash
docker compose exec -T db pg_dump -U "${DB_USER:-devuser}" "${DB_NAME:-devcheck}" > "backup_$(date +%Y%m%d_%H%M%S).sql"
```

Then update only the application container:

```bash
docker compose build devcheck-bot
docker compose up -d --no-deps devcheck-bot
docker compose logs --tail=150 devcheck-bot
```

The bind-mounted `./pgdata` directory is not replaced by this operation. Startup
migrations use additive, idempotent operations and do not automatically run
`DROP`, `TRUNCATE`, or user-data cleanup statements. Rollback consists of
starting the previous application image; the Mini App changes do not require a
database rollback.

After deployment, fully close and reopen the Telegram Mini App, then verify:

1. Existing resources load and problem-first sorting is active.
2. The status counters filter the resource list.
3. The add dialog closes using its close button, Telegram Back, Escape, and a
   backdrop tap where supported.
4. Adding a temporary public domain completes within the configured DNS timeout.
5. Pause, resume, manual check, and delete affect only the current user's site.
6. Feedback closes the Mini App, captures text and attachments in the bot,
   displays them under `/admin/feedback`, and delivers an administrator reply.
7. Bot polling, scheduled monitoring, admin console, and remote agents continue
   to operate.

## Local Development and Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m bot.main
```

Run the automated checks:

```bash
python -m unittest discover -s tests -v
python -m compileall -q bot agent tests
```

More detail is available in [ARCHITECTURE.md](ARCHITECTURE.md) and
[docs/architecture-review.md](docs/architecture-review.md).
