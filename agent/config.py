import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    country: str
    region: str
    provider: str
    server_ws_url: str
    token: str
    heartbeat_seconds: int
    reconnect_min_seconds: int
    reconnect_max_seconds: int
    max_concurrent_checks: int
    check_timeout_seconds: int


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def load_config() -> AgentConfig:
    load_dotenv()
    return AgentConfig(
        agent_id=os.getenv("AGENT_ID", "agent-local"),
        country=os.getenv("AGENT_COUNTRY", "unknown"),
        region=os.getenv("AGENT_REGION", ""),
        provider=os.getenv("AGENT_PROVIDER", ""),
        server_ws_url=os.getenv("SERVER_WS_URL", ""),
        token=os.getenv("AGENT_TOKEN", ""),
        heartbeat_seconds=_int_env("AGENT_HEARTBEAT_SECONDS", 30),
        reconnect_min_seconds=_int_env("AGENT_RECONNECT_MIN_SECONDS", 2),
        reconnect_max_seconds=_int_env("AGENT_RECONNECT_MAX_SECONDS", 60),
        max_concurrent_checks=_int_env("AGENT_MAX_CONCURRENT_CHECKS", 5),
        check_timeout_seconds=_int_env("AGENT_CHECK_TIMEOUT_SECONDS", 45),
    )
