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
        self._pending = {}
        self._lock = asyncio.Lock()

    async def register(self, agent: AgentConnection):
        old_ws = None
        async with self._lock:
            old = self._agents.get(agent.agent_id)
            if old and old.ws is not agent.ws:
                old_ws = old.ws
            self._agents[agent.agent_id] = agent
        if old_ws:
            await old_ws.close(message=b"replaced by new connection")

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
        future = None
        async with self._lock:
            now = utc_now()
            if agent_id in self._agents:
                self._agents[agent_id].last_seen_at = now
                self._agents[agent_id].last_result_at = now
            future = self._pending.pop(payload.get("job_id"), None)
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
        if future and not future.done():
            future.set_result(payload)

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

    async def request_check(self, agent_id: str, url: str, checks=None, timeout_sec=30):
        loop = asyncio.get_running_loop()
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
            future = loop.create_future()
            self._pending[payload["job_id"]] = future
            await agent.ws.send_json(payload)

        try:
            return await asyncio.wait_for(future, timeout=timeout_sec + 5)
        except Exception:
            async with self._lock:
                self._pending.pop(payload["job_id"], None)
            raise

    async def request_check_all(self, url: str, checks=None, timeout_sec=30):
        agents = await self.list_agents()
        tasks = [
            self._request_check_or_error(agent, url, checks=checks, timeout_sec=timeout_sec)
            for agent in agents
        ]
        if not tasks:
            return []
        return await asyncio.gather(*tasks)

    async def _request_check_or_error(self, agent: dict, url: str, checks=None, timeout_sec=30):
        try:
            return await self.request_check(
                agent["agent_id"],
                url,
                checks=checks,
                timeout_sec=timeout_sec,
            )
        except Exception as e:
            return {
                "type": "check.result",
                "job_id": None,
                "agent_id": agent["agent_id"],
                "country": agent.get("country"),
                "region": agent.get("region"),
                "provider": agent.get("provider"),
                "url": url,
                "ok": False,
                "http": None,
                "ssl_days": None,
                "domain_days": None,
                "registrar": None,
                "contact_url": None,
                "error": f"{type(e).__name__}: {e}",
            }


AGENT_REGISTRY = AgentRegistry()
