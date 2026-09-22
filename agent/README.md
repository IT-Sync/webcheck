# Webcheck Remote Agent

The remote agent runs on a separate server, opens an outbound authenticated
WebSocket connection to the central Webcheck service, receives check jobs, and
returns results from its own network and location.

## Quick Start

1. Create the agent configuration:

   ```bash
   cp .env.example .env
   ```

2. Set `SERVER_WS_URL`, `AGENT_TOKEN`, `AGENT_ID`, and `AGENT_COUNTRY`. The token
   must match the central server's `AGENT_WS_TOKEN`.

   For a public TLS endpoint:

   ```env
   SERVER_WS_URL=wss://webcheck.example.com/ws/agents
   ```

   For an agent container connecting directly to the central host without TLS:

   ```env
   SERVER_WS_URL=ws://10.1.0.4:11001/ws/agents
   ```

3. Build and start the container:

   ```bash
   docker compose up -d --build
   docker compose logs -f webcheck-agent
   ```

The central production listener uses `AGENT_WS_PORT=11001`. Do not point an agent
at the Mini App/admin port `11003`.

## Configuration

```env
AGENT_ID=mars-moscow
AGENT_COUNTRY=RU
AGENT_REGION=Moscow
AGENT_PROVIDER=
SERVER_WS_URL=wss://webcheck.example.com/ws/agents
AGENT_TOKEN=replace_with_the_central_agent_token

AGENT_HEARTBEAT_SECONDS=30
AGENT_RECONNECT_MIN_SECONDS=2
AGENT_RECONNECT_MAX_SECONDS=60
AGENT_MAX_CONCURRENT_CHECKS=5
AGENT_CHECK_TIMEOUT_SECONDS=45
HTTP_ALLOW_PLAIN_FALLBACK=1
```

The agent reconnects with bounded backoff and sends heartbeats over the existing
connection. It does not require an inbound port.

## Protocol

After connecting, the agent sends:

```json
{
  "type": "agent.hello",
  "agent_id": "mars-moscow",
  "country": "RU",
  "region": "Moscow",
  "provider": "",
  "token": "shared-agent-secret"
}
```

The server sends a check request:

```json
{
  "type": "check.request",
  "job_id": "uuid",
  "url": "https://example.com",
  "checks": ["http", "ssl", "domain"],
  "timeout_sec": 30
}
```

The agent returns:

```json
{
  "type": "check.result",
  "job_id": "uuid",
  "agent_id": "mars-moscow",
  "country": "RU",
  "region": "Moscow",
  "ok": true,
  "http": {
    "ok": true,
    "status_code": 200,
    "latency_ms": 120,
    "ip": "203.0.113.10"
  },
  "ssl_days": 47,
  "domain_days": 348,
  "registrar": "Example Registrar",
  "contact_url": null,
  "error": null
}
```

See `../ARCHITECTURE.md` for routing, authentication, and compatibility
details.
