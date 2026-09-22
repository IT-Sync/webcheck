import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from bot.core.url_utils import normalize_url


class TargetValidationError(ValueError):
    """Raised when a monitoring target is invalid or unsafe."""


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global


async def validate_monitoring_target(value: str, *, dns_timeout_seconds: float = 3) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetValidationError("Укажите домен или адрес сайта")

    normalized = normalize_url(value)
    hostname = urlparse(normalized).hostname
    if not hostname or "." not in hostname:
        raise TargetValidationError("Укажите корректный публичный домен")

    try:
        addresses = await asyncio.wait_for(
            asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                443,
                type=socket.SOCK_STREAM,
            ),
            timeout=dns_timeout_seconds,
        )
    except TimeoutError as exc:
        raise TargetValidationError("DNS-сервер отвечает слишком долго. Попробуйте ещё раз") from exc
    except socket.gaierror as exc:
        raise TargetValidationError("Домен не удалось найти в DNS") from exc

    resolved = {row[4][0] for row in addresses}
    if not resolved or any(not is_public_address(address) for address in resolved):
        raise TargetValidationError("Локальные и приватные адреса нельзя добавить в мониторинг")
    return normalized
