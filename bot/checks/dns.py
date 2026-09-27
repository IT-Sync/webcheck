"""DNS snapshot collection for successful central checks."""

import asyncio
from urllib.parse import urlparse

import dns.exception
import dns.resolver


def _normalized_names(answer):
    return sorted({str(record.target).rstrip(".").lower() for record in answer})


def _resolve_dns_snapshot_sync(url, resolved_ips, timeout_seconds):
    hostname = urlparse(url).hostname
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout_seconds
    labels = hostname.rstrip(".").split(".")
    nameservers = None
    zone = None
    for offset in range(max(1, len(labels) - 1)):
        candidate = ".".join(labels[offset:])
        try:
            nameservers = _normalized_names(resolver.resolve(candidate, "NS"))
            zone = candidate
            break
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except (dns.exception.Timeout, dns.resolver.NoNameservers):
            return {"ips": sorted(set(resolved_ips)), "ns": None, "mx": None}

    mail_exchangers = None
    if zone:
        try:
            mail_exchangers = sorted({
                f"{int(record.preference)} {str(record.exchange).rstrip('.').lower()}"
                for record in resolver.resolve(zone, "MX")
            })
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            mail_exchangers = []
        except (dns.exception.Timeout, dns.resolver.NoNameservers):
            mail_exchangers = None
    return {
        "ips": sorted(set(resolved_ips)),
        "ns": nameservers,
        "mx": mail_exchangers,
    }


async def resolve_dns_snapshot(url, resolved_ips, timeout_seconds=5):
    """Resolve IP, authoritative NS, and MX values without blocking asyncio."""
    return await asyncio.to_thread(
        _resolve_dns_snapshot_sync, url, resolved_ips, timeout_seconds,
    )
