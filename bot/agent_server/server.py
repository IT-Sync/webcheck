import os

from aiohttp import WSMsgType, web

from bot.agent_server.registry import AGENT_REGISTRY, AgentConnection


AGENT_WS_TOKEN = os.getenv("AGENT_WS_TOKEN")
AGENT_WS_HOST = os.getenv("AGENT_WS_HOST", "0.0.0.0")
AGENT_WS_PORT = int(os.getenv("AGENT_WS_PORT", "8090"))
AGENT_WS_PATH = os.getenv("AGENT_WS_PATH", "/ws/agents")


def _remote(request: web.Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    peername = request.transport.get_extra_info("peername") if request.transport else None
    return peername[0] if peername else ""


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "webcheck-agent-ws"})


async def agents_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=45)
    await ws.prepare(request)

    agent_id = None
    try:
        hello = await ws.receive_json(timeout=15)
        if hello.get("type") != "agent.hello":
            await ws.send_json({"type": "agent.error", "error": "first message must be agent.hello"})
            await ws.close()
            return ws

        if not AGENT_WS_TOKEN or hello.get("token") != AGENT_WS_TOKEN:
            await ws.send_json({"type": "agent.error", "error": "unauthorized"})
            await ws.close()
            return ws

        agent_id = str(hello.get("agent_id") or "").strip()
        if not agent_id:
            await ws.send_json({"type": "agent.error", "error": "agent_id is required"})
            await ws.close()
            return ws

        if await AGENT_REGISTRY.is_disabled(agent_id):
            await ws.send_json({"type": "agent.disabled", "agent_id": agent_id})
            await ws.close(message=b"agent disabled")
            return ws

        agent = AgentConnection(
            agent_id=agent_id,
            country=str(hello.get("country") or "unknown"),
            region=str(hello.get("region") or ""),
            provider=str(hello.get("provider") or ""),
            ws=ws,
            remote=_remote(request),
        )
        await AGENT_REGISTRY.register(agent)
        await ws.send_json({"type": "agent.ack", "agent_id": agent_id})
        print(f"Agent connected: {agent_id} {agent.country} {agent.region}".strip())

        async for message in ws:
            if message.type == WSMsgType.TEXT:
                try:
                    payload = message.json()
                except Exception:
                    await ws.send_json({"type": "agent.error", "error": "invalid json"})
                    continue

                message_type = payload.get("type")
                if message_type == "agent.ping":
                    await AGENT_REGISTRY.touch(agent_id)
                    await ws.send_json({"type": "server.pong"})
                elif message_type == "check.result":
                    await AGENT_REGISTRY.record_result(agent_id, payload)
                else:
                    await ws.send_json({"type": "agent.error", "error": f"unsupported message type: {message_type}"})
            elif message.type == WSMsgType.ERROR:
                print(f"Agent websocket error {agent_id}: {ws.exception()}")
    except Exception as e:
        print(f"Agent connection failed {agent_id or 'unknown'}: {type(e).__name__}: {e}")
    finally:
        if agent_id:
            await AGENT_REGISTRY.unregister(agent_id, ws=ws)
            print(f"Agent disconnected: {agent_id}")

    return ws


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get(AGENT_WS_PATH, agents_ws)
    return app


async def start_agent_ws_server():
    if not AGENT_WS_TOKEN:
        print("Agent WebSocket server disabled: AGENT_WS_TOKEN is not set")
        return None

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, AGENT_WS_HOST, AGENT_WS_PORT)
    await site.start()
    print(f"Agent WebSocket server started on ws://{AGENT_WS_HOST}:{AGENT_WS_PORT}{AGENT_WS_PATH}")
    return runner
