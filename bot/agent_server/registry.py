import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc)


@dataclass
class AgentConnection:
    agent_id: str
    country: str
    region: str
    provider: str
    ws: object
    connected_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    last_result_at: datetime | None = None
    remote: str | None = None


class AgentRegistry:
    def __init__(self):
        self._agents = {}
        self._recent_results = []
        self._lock = asyncio.Lock()

    async def register(self, agent: AgentConnection):
        async with self._lock:
            old = self._agents.get(agent.agent_id)
            if old and old.ws is not agent.ws:
                await old.ws.close(message=b"replaced by new connection")
            self._agents[agent.agent_id] = agent

    async def unregister(self, agent_id: str, ws=None):
        async with self._lock:
            current = self._agents.get(agent_id)
            if current and (ws is None or current.ws is ws):
                self._agents.pop(agent_id, None)

    async def touch(self, agent_id: str):
        async with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].last_seen_at = utc_now()

    async def record_result(self, agent_id: str, payload: dict):
        async with self._lock:
            now = utc_now()
            if agent_id in self._agents:
                self._agents[agent_id].last_seen_at = now
                self._agents[agent_id].last_result_at = now
            row = {
                "received_at": now,
                "agent_id": agent_id,
                "job_id": payload.get("job_id"),
                "url": payload.get("url"),
                "ok": payload.get("ok"),
                "country": payload.get("country"),
                "region": payload.get("region"),
                "error": payload.get("error"),
            }
            self._recent_results.insert(0, row)
            del self._recent_results[100:]

    async def list_agents(self):
        async with self._lock:
            return [
                {
                    "agent_id": agent.agent_id,
                    "country": agent.country,
                    "region": agent.region,
                    "provider": agent.provider,
                    "connected_at": agent.connected_at,
                    "last_seen_at": agent.last_seen_at,
                    "last_result_at": agent.last_result_at,
                    "remote": agent.remote,
                }
                for agent in sorted(self._agents.values(), key=lambda item: item.agent_id)
            ]

    async def recent_results(self):
        async with self._lock:
            return list(self._recent_results)

    async def send_check(self, agent_id: str, url: str, checks=None, timeout_sec=30):
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise KeyError(f"Agent {agent_id} is not online")
            payload = {
                "type": "check.request",
                "job_id": str(uuid4()),
                "url": url,
                "checks": checks or ["http", "ssl", "domain"],
                "timeout_sec": timeout_sec,
            }
            await agent.ws.send_json(payload)
            return payload["job_id"]


AGENT_REGISTRY = AgentRegistry()
