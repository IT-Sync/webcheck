import os

from bot.core.url_utils import is_valid_monitoring_url
from bot.agent_server.registry import AGENT_REGISTRY


AGENT_CHECKS_ENABLED = os.getenv("AGENT_CHECKS_ENABLED", "1") == "1"
AGENT_CHECK_TIMEOUT_SECONDS = int(os.getenv("AGENT_CHECK_TIMEOUT_SECONDS", "30"))


async def check_with_agents(url: str, checks=None, timeout_sec=None):
    if not AGENT_CHECKS_ENABLED or not is_valid_monitoring_url(url):
        return []
    return await AGENT_REGISTRY.request_check_all(
        url,
        checks=checks or ["http"],
        timeout_sec=timeout_sec or AGENT_CHECK_TIMEOUT_SECONDS,
    )
