"""Public monitoring-target validation shared by creation and check paths."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from bot.core.url_utils import is_valid_monitoring_url, normalize_url


class TargetValidationError(ValueError):
    """Raised when a monitoring target is invalid or unsafe."""


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global


def _resolve_addresses(hostname, port):
    rows = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return sorted({row[4][0] for row in rows})


async def resolve_public_addresses(url: str, *, dns_timeout_seconds: float = 3) -> list[str]:
    if not is_valid_monitoring_url(url):
        raise TargetValidationError("Укажите корректный публичный HTTP(S) адрес")
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname or "." not in hostname:
        raise TargetValidationError("Укажите корректный публичный домен")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = await asyncio.wait_for(
            asyncio.to_thread(_resolve_addresses, hostname, port),
            timeout=dns_timeout_seconds,
        )
    except TimeoutError as exc:
        raise TargetValidationError("DNS-сервер отвечает слишком долго. Попробуйте ещё раз") from exc
    except socket.gaierror as exc:
        raise TargetValidationError("Домен не удалось найти в DNS") from exc
    if not resolved or any(not is_public_address(address) for address in resolved):
        raise TargetValidationError("Локальные и приватные адреса нельзя добавить в мониторинг")
    return resolved


async def validate_monitoring_target(value: str, *, dns_timeout_seconds: float = 3) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetValidationError("Укажите домен или адрес сайта")
    normalized = normalize_url(value)
    await resolve_public_addresses(normalized, dns_timeout_seconds=dns_timeout_seconds)
    return normalized
