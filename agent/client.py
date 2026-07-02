import asyncio
import json

import aiohttp

from agent.checks import run_check
from agent.config import AgentConfig
from agent.protocol import error_result, heartbeat_message, hello_message


class AgentClient:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.semaphore = asyncio.Semaphore(config.max_concurrent_checks)
        self.tasks = set()

    async def run_forever(self):
        if not self.config.server_ws_url:
            raise RuntimeError("SERVER_WS_URL is required")
        if not self.config.token:
            raise RuntimeError("AGENT_TOKEN is required")

        delay = self.config.reconnect_min_seconds
        while True:
            try:
                await self._connect_once()
                delay = self.config.reconnect_min_seconds
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"Agent connection failed: {type(e).__name__}: {e}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.reconnect_max_seconds)

    async def _connect_once(self):
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(self.config.server_ws_url, heartbeat=None) as ws:
                print(f"Connected to {self.config.server_ws_url}")
                await ws.send_json(hello_message(self.config))
                heartbeat_task = asyncio.create_task(self._heartbeat(ws))
                try:
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(ws, message.data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise ws.exception() or RuntimeError("WebSocket error")
                        elif message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            break
                finally:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                    for task in list(self.tasks):
                        task.cancel()
                    await asyncio.gather(*self.tasks, return_exceptions=True)
                    self.tasks.clear()

    async def _heartbeat(self, ws):
        while True:
            await asyncio.sleep(self.config.heartbeat_seconds)
            await ws.send_json(heartbeat_message(self.config))

    async def _handle_message(self, ws, raw: str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print(f"Ignoring invalid JSON message: {raw[:200]}")
            return

        message_type = payload.get("type")
        if message_type == "check.request":
            task = asyncio.create_task(self._handle_check(ws, payload))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        elif message_type in {"server.pong", "agent.ack"}:
            return
        else:
            print(f"Ignoring unsupported message type: {message_type}")

    async def _handle_check(self, ws, payload: dict):
        async with self.semaphore:
            job_id = payload.get("job_id")
            url = payload.get("url")
            timeout = int(payload.get("timeout_sec") or self.config.check_timeout_seconds)
            try:
                result = await asyncio.wait_for(run_check(self.config, payload), timeout=timeout)
            except Exception as e:
                result = error_result(self.config, job_id, url, f"{type(e).__name__}: {e}")
            await ws.send_json(result)
