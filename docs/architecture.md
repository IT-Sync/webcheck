# Architecture

## Current Modules

- `bot/main.py` - application entrypoint.
- `bot/telegram/` - Telegram handlers, callbacks, scheduler and notification flow.
- `bot/checks/` - HTTP, SSL, WHOIS, GeoIP and subdomain checks.
- `bot/checks/service.py` - shared resource check service used by UI layers and future agents.
- `bot/infra/` - infrastructure adapters such as PostgreSQL access.
- `bot/core/` - shared formatting and URL helpers.

Top-level modules such as `bot/monitor.py` and `bot/db.py` are compatibility wrappers for older imports.

## Agent Project Direction

The next project should be a separate agent process that connects to the central server by websocket.

Recommended connection direction: agent initiates the websocket connection to the server.

Reasons:

- agents can run behind NAT, firewalls or home/provider networks without inbound ports;
- the server keeps one registry of online agents and their country/region metadata;
- assignments are delivered through existing authenticated connections;
- reconnect/backoff and heartbeat logic live on the agent side, where network instability is most likely.

High-level flow:

1. Agent starts and connects to `wss://server/ws/agents`.
2. Agent authenticates with token, `agent_id`, country and optional region/provider metadata.
3. Server marks the agent online and sends check jobs.
4. Agent performs checks and returns structured results.
5. Server stores results and sends the user one combined message, for example:
   `Проверка из Server A, RU: ...` and `Проверка из Server B, DE: ...`.

Suggested job payload:

```json
{
  "type": "check.request",
  "job_id": "uuid",
  "url": "https://example.com",
  "checks": ["http", "ssl", "domain"],
  "timeout_sec": 30
}
```

Suggested result payload:

```json
{
  "type": "check.result",
  "job_id": "uuid",
  "agent_id": "server-a",
  "country": "RU",
  "ok": true,
  "http": {
    "ok": true,
    "status_code": 200,
    "latency_ms": 120,
    "ip": "203.0.113.10"
  },
  "ssl_days": 42,
  "domain_days": 180,
  "error": null
}
```
