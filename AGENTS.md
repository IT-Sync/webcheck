# AGENTS.md

Instructions for AI agents working in the Webcheck repository. These instructions
apply to the entire repository unless a more deeply nested `AGENTS.md` overrides
them.

## Project Overview

Webcheck is an asynchronous Telegram bot that monitors HTTP availability, SSL
certificate expiration, and domain registration expiration. The main application
stores state in PostgreSQL, sends notifications through aiogram, runs scheduled
jobs with APScheduler, hosts an administrative web console, and exposes a
WebSocket server for remote checking agents. The `agent/` directory contains a
separate application that connects to the central server through an outbound
WebSocket connection.

## Repository Map

- `bot/main.py` — entry point for the central application.
- `bot/telegram/` — Telegram handlers, callback data, scheduler, and message
  tracking.
- `bot/checks/` — HTTP, SSL, WHOIS, GeoIP, and subdomain checks.
- `bot/core/` — pure formatters and URL helpers; prefer this package for logic
  that does not depend on Telegram, the network, or the database.
- `bot/infra/db.py` — schema, migrations, and the synchronous PostgreSQL access
  layer.
- `bot/admin_console/` — aiohttp administrative console.
- `bot/agent_server/` — WebSocket server and connected-agent registry.
- `agent/` — standalone remote agent with its own Dockerfile, Compose file, and
  dependencies.
- `tests/` — unit tests based on the standard-library `unittest` framework.
- `ARCHITECTURE.md` — authoritative architecture, topology, and protocol map.
- `PROJECT_MEMORY.md` — authoritative snapshot of current project state.
- `TODO.md` — unfinished work, known limitations, and technical debt.

The files `bot/db.py`, `bot/handlers.py`, `bot/monitor.py`, `bot/scheduler.py`,
`bot/status_formatter.py`, `bot/subfinder.py`, `bot/url_utils.py`, and
`bot/callback_data.py` are compatibility wrappers. Put new implementation code in
the corresponding packages, but do not remove the wrappers or break legacy
imports unless the task explicitly calls for a breaking change.

## Language and Communication

- Write all notes, plans, code comments, documentation, commit messages, and other
  repository-facing text in English.
- Respond to the user in Russian unless the user explicitly requests another
  language.

## Persistent Project Memory

- `PROJECT_MEMORY.md` is the primary authoritative snapshot of the current
  project state, behavior, constraints, decisions, and deployment assumptions.
- `ARCHITECTURE.md` is the authoritative reference for architecture, component
  boundaries, data flow, infrastructure, integrations, authentication,
  networking, and deployment topology.
- `TODO.md` is the authoritative tracker for unfinished work, known bugs,
  limitations, and technical debt.
- Always read `PROJECT_MEMORY.md` before substantial work.
- Read `TODO.md` when work concerns current priorities, bugs, limitations, or
  unfinished work.
- Read `ARCHITECTURE.md` before changing architecture, infrastructure,
  integrations, deployment, APIs, storage, authentication, networking,
  background processing, or major components.
- Do not rescan the repository when project memory already contains the needed
  context. Inspect only the relevant implementation unless broader inspection
  is necessary to verify or complete the task.
- If memory conflicts with code or configuration, verify the implementation and
  correct the memory. Never preserve stale documentation.

## Required Workflow for Substantial Tasks

1. Read this file and `PROJECT_MEMORY.md`.
2. Read `TODO.md` and/or `ARCHITECTURE.md` when the task touches their scope.
3. Inspect the relevant implementation.
4. Perform and validate the requested work.
5. Check whether functionality, status, decisions, configuration, operations,
   architecture, issues, limitations, or priorities changed.
6. Update every affected memory file in the same task before the final response.

A substantial task is incomplete while relevant memory is stale. Do not wait for
the user to request memory maintenance. Tiny typo fixes, formatting-only changes,
and behavior-neutral refactoring do not require memory updates.

## Memory Update Rules

- Update `PROJECT_MEMORY.md` when functionality, project status, features,
  components, dependencies, configuration, runtime behavior, integrations,
  constraints, known issues, limitations, decisions, deployment assumptions,
  active work, or next steps change.
- Update `ARCHITECTURE.md` when component boundaries, communication, APIs, data
  flow, storage, authentication or authorization, external systems,
  infrastructure, networking, runtime topology, deployment, workers, schedules,
  queues, caches, or CI/CD change.
- Update `TODO.md` when work is completed, discovered, reprioritized, made
  obsolete, or when bugs or technical debt are introduced or resolved.
- Keep memory concise and current. Record durable facts and decisions rather
  than a chronological activity log.

## Environment Setup

Work from the repository root. For a local environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

The standalone agent has its own dependencies in `agent/requirements.txt` and an
example configuration in `agent/.env.example`. Never commit `.env` files,
Telegram tokens, `ADMIN_WEB_TOKEN`, `AGENT_WS_TOKEN`/`AGENT_TOKEN`, database
dumps, or the `pgdata/` directory.

Start the full central stack with:

```bash
docker compose up -d --build
```

Start the remote agent separately from the `agent/` directory with the same
command:

```bash
docker compose up -d --build
```

## Validation

Run at least these checks after changing Python code:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q bot agent tests
```

Inside an activated virtual environment, `python` may be used instead of
`python3`. The repository does not currently configure a formatter, linter, or
type checker. Do not introduce a new mandatory tool or perform repository-wide
formatting without a dedicated task.

Add or update tests for changed behavior. Prefer fast unit tests around pure
functions; mock external HTTP, DNS, WHOIS, Telegram, WebSocket, and PostgreSQL
calls. If a change requires an integration test, clearly document the required
services and environment variables.

`bot.infra.db` opens a PostgreSQL connection at import time. Do not import it in
isolated unit tests without a prepared database or a substituted dependency.
Starting the complete application also requires an available PostgreSQL instance
and a valid `BOT_TOKEN`.

## Change Guidelines

- Preserve Python 3.11 compatibility and the existing asynchronous style.
- Do not run blocking network or disk I/O directly in the event loop. Use async
  clients or `asyncio.to_thread` for unavoidable synchronous APIs.
- Use `bot.checks.service.check_resource` for resource checks shared by UI and
  scheduler flows unless the task specifically needs a lower-level primitive.
- Telegram callback data must remain stable and fit within the 64-byte limit.
  Update builders, handlers, and tests together when changing it.
- Respect Telegram message-size limits. Pass long reports through the existing
  splitting helpers in `bot.core.status_formatter`.
- Escape user-provided and external values before inserting them into admin
  console HTML. Do not weaken token-based authentication for administrative or
  agent endpoints.
- Normalize URLs and domain names through the central helpers. Do not create a
  second implementation next to an existing helper without a clear need.
- Synchronize logic shared conceptually by the central server and remote agent
  deliberately: network-check implementations currently exist in both
  `bot/checks/` and `agent/checks.py`.
- Treat the WebSocket message format as an external contract. When adding fields,
  retain compatibility with older agents and update both sides, the examples in
  `agent/README.md`, and `ARCHITECTURE.md` when appropriate.
- Do not rename Docker Compose services, entry points, or environment variables
  without updating the Dockerfiles, Compose files, `.env.example`, and README.

## PostgreSQL and Migrations

- Always use psycopg2 `%s` parameters for values. Never interpolate user input
  into SQL strings.
- Commit writes. For new multi-step operations, ensure failures trigger a
  rollback.
- The schema is created and extended from `bot/infra/db.py`. Startup migrations
  must remain idempotent and additive, using constructs such as `IF NOT EXISTS`.
  Do not add automatic `DROP`, `TRUNCATE`, or user-data cleanup operations.
- When changing the selected columns or their order in a query, find every result
  consumer. Some code accesses rows by positional index, while other code uses
  dictionary-style access.
- The global `conn` and `cursor` are an existing architectural constraint. Do not
  increase concurrent access through the single cursor. Treat a migration to a
  pool or async driver as a separate, thoroughly tested refactor.

## Scheduler and Notifications

Monitoring processes sites concurrently under `MAX_CONCURRENT_CHECKS`, while
APScheduler limits overlapping runs through `MONITOR_MAX_INSTANCES`. Avoid
duplicate DOWN, RECOVERY, and expiry notifications: preserve the semantics of
notification flags, `http_fail_count`, incident timestamps, and the confirming
HTTP check. A failure for one site or an unavailable remote agent must not abort
processing for the remaining sites.

Every new configuration option must have a safe default, be added to the relevant
`.env.example`, and be documented in the README when operators need to know about
it.

## Before Completing a Task

1. Review `git diff` and confirm that it contains no secrets, generated files, or
   unrelated changes.
2. Run the unit tests and `compileall` commands listed above.
3. For schema, Docker, scheduler, Telegram UI, or agent protocol changes, also
   validate the affected workflow or clearly state what could not be tested and
   why.
4. Keep the README, `.env.example`, and architecture documentation synchronized
   with changes to public behavior or configuration.
5. Update `PROJECT_MEMORY.md`, `ARCHITECTURE.md`, and `TODO.md` when required by
   the persistent-memory workflow above.
