from datetime import datetime, timezone

from agent.config import AgentConfig


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hello_message(config: AgentConfig) -> dict:
    return {
        "type": "agent.hello",
        "agent_id": config.agent_id,
        "country": config.country,
        "region": config.region,
        "provider": config.provider,
        "token": config.token,
        "sent_at": utc_now_iso(),
    }


def heartbeat_message(config: AgentConfig) -> dict:
    return {
        "type": "agent.ping",
        "agent_id": config.agent_id,
        "sent_at": utc_now_iso(),
    }


def error_result(config: AgentConfig, job_id, url, error: str) -> dict:
    return {
        "type": "check.result",
        "job_id": job_id,
        "agent_id": config.agent_id,
        "country": config.country,
        "region": config.region,
        "provider": config.provider,
        "url": url,
        "ok": False,
        "http": None,
        "ssl_days": None,
        "domain_days": None,
        "registrar": None,
        "contact_url": None,
        "error": error,
        "finished_at": utc_now_iso(),
    }
