from dataclasses import dataclass

from bot.checks.monitor import check_domain_expiry, check_http_details, check_ssl


@dataclass(frozen=True)
class ResourceCheckResult:
    url: str
    http: dict
    ssl_days: int
    domain_days: int
    registrar: str | None = None
    contact_url: str | None = None
    country: str | None = None
    agent_id: str | None = None


async def check_resource(
    url: str,
    *,
    include_domain: bool = True,
    country: str | None = None,
    agent_id: str | None = None,
) -> ResourceCheckResult:
    http = await check_http_details(url)
    ssl_days = await check_ssl(url)
    if include_domain:
        domain_days, registrar, contact_url = await check_domain_expiry(url)
    else:
        domain_days, registrar, contact_url = -1, None, None
    return ResourceCheckResult(
        url=url,
        http=http,
        ssl_days=ssl_days,
        domain_days=domain_days,
        registrar=registrar,
        contact_url=contact_url,
        country=country,
        agent_id=agent_id,
    )
