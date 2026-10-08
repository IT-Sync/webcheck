import aiohttp
from aiohttp.abc import AbstractResolver
import ssl
import socket
import asyncio
import re
import os
import time
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from urllib.parse import urlparse

from bot.core.url_utils import is_valid_monitoring_url
from bot.core.content_checks import evaluate_response, has_content_assertions
from bot.core.target_validation import TargetValidationError, resolve_public_addresses

MAX_RESPONSE_BODY_BYTES = 1024 * 1024


def resolve_hostname(url):
    hostname = urlparse(url).hostname
    if not hostname:
        return None
    try:
        return socket.gethostbyname(hostname)
    except socket.error:
        return None

class _StaticResolver(AbstractResolver):
    """Pin an already validated public DNS result for the request lifetime."""

    def __init__(self, hostname, addresses):
        self.hostname = hostname
        self.addresses = addresses

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        if host != self.hostname:
            raise OSError("Unexpected redirect hostname")
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for address in self.addresses
        ]

    async def close(self):
        return None


#async def check_http(url):
#    try:
#        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
#            async with session.get(url) as resp:
#                return resp.status == 200
#    except:
#        return False

#async def check_http(url, retries=3, delay=10):
#    timeout = aiohttp.ClientTimeout(total=15)
#    headers = {"User-Agent": "Mozilla/5.0 (compatible; DevCheckBot/1.0)"}
#
#    for attempt in range(retries):
#        try:
#            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
#                async with session.get(url, allow_redirects=True) as resp:
#                    if 200 <= resp.status < 300:
#                        return True
#        except Exception as e:
#            print(f"[Attempt {attempt+1}] Error checking {url}: {e}")
#        await asyncio.sleep(delay)
#
#    return False

async def check_http_details(
    url, retries=3, delay=5, timeout_seconds=12, check_settings=None,
    dns_timeout_seconds=3,
):
    check_settings = check_settings or {}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/113.0.0.0 Safari/537.36 "
            "@ITSync_WebCheckBot"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }

    allow_http_fallback = os.getenv("HTTP_ALLOW_PLAIN_FALLBACK", "1") == "1"
    try:
        resolved_ips = await resolve_public_addresses(
            url, dns_timeout_seconds=dns_timeout_seconds,
        )
    except TargetValidationError as exc:
        return {
            "ok": False,
            "status_code": None,
            "method": None,
            "url": url,
            "latency_ms": None,
            "attempts": 0,
            "error": str(exc),
            "ip": None,
            "resolved_ips": [],
            "target_validation_failed": True,
        }
    hostname = urlparse(url).hostname
    resolved_ip = resolved_ips[0]
    urls_to_try = [url]
    if allow_http_fallback and url.startswith("https://"):
        urls_to_try.append("http://" + url[len("https://"):])

    connector = aiohttp.TCPConnector(
        ssl=False,
        limit=10,
        resolver=_StaticResolver(hostname, resolved_ips),
        use_dns_cache=True,
    )
    last_error = None
    attempts = 0
    last_status_code = None
    last_method = None
    last_latency_ms = None
    requires_get = has_content_assertions(check_settings)
    requires_body = bool(check_settings.get("required_text") or check_settings.get("json_assertions"))
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
        connector=connector,
        max_field_size=65536
    ) as session:
        for attempt in range(1, retries + 1):
            for current_url in urls_to_try:
                try:
                    for method in (("GET",) if requires_get else ("HEAD", "GET")):
                        attempts += 1
                        started = time.monotonic()
                        async with session.request(method, current_url, allow_redirects=False) as resp:
                            latency_ms = int((time.monotonic() - started) * 1000)
                            last_status_code = resp.status
                            last_method = method
                            last_latency_ms = latency_ms
                            print(f"[Attempt {attempt}] {method} {resp.status} for {current_url}")
                            if requires_get:
                                raw_body = (await resp.content.read(MAX_RESPONSE_BODY_BYTES + 1)
                                            if requires_body else b"")
                                if len(raw_body) > MAX_RESPONSE_BODY_BYTES:
                                    last_error = "Тело ответа превышает 1 МБ"
                                    break
                                body = raw_body.decode(resp.charset or "utf-8", errors="replace")
                                assertion_error = evaluate_response(
                                    resp.status, body, check_settings,
                                )
                                if assertion_error is None:
                                    return {
                                        "ok": True,
                                        "status_code": resp.status,
                                        "method": method,
                                        "url": current_url,
                                        "latency_ms": latency_ms,
                                        "attempts": attempts,
                                        "error": None,
                                        "ip": resolved_ip,
                                        "resolved_ips": resolved_ips,
                                    }
                                last_error = assertion_error
                                break
                            # 4xx означает, что сервер отвечает, но может блокировать ботов/доступ.
                            # Для мониторинга доступности это считаем "сайт жив".
                            if 200 <= resp.status < 500:
                                return {
                                    "ok": True,
                                    "status_code": resp.status,
                                    "method": method,
                                    "url": current_url,
                                    "latency_ms": latency_ms,
                                    "attempts": attempts,
                                    "error": None,
                                    "ip": resolved_ip,
                                    "resolved_ips": resolved_ips,
                                }

                            # Если HEAD не дал положительный ответ, пробуем GET.
                            if method == "HEAD":
                                continue
                            last_error = f"HTTP {resp.status}"
                            break
                except Exception as e:
                    error_text = str(e)
                    if "Header value is too long" in error_text and not requires_get:
                        return {
                            "ok": True,
                            "status_code": None,
                            "method": method,
                            "url": current_url,
                            "latency_ms": None,
                            "attempts": attempts,
                            "error": "Header value is too long",
                            "ip": resolved_ip,
                            "resolved_ips": resolved_ips,
                        }
                    last_error = error_text or type(e).__name__
                    print(f"[Attempt {attempt}] Error checking {current_url}: {error_text or type(e).__name__}")

            if attempt < retries:
                await asyncio.sleep(delay * attempt)

    return {
        "ok": False,
        "status_code": last_status_code,
        "method": last_method,
        "url": urls_to_try[-1],
        "latency_ms": last_latency_ms,
        "attempts": attempts,
        "error": last_error or "No successful HTTP response",
        "ip": resolved_ip,
        "resolved_ips": resolved_ips,
    }


async def check_http(url, retries=3, delay=5, timeout_seconds=12):
    details = await check_http_details(url, retries=retries, delay=delay, timeout_seconds=timeout_seconds)
    return details["ok"]


def _check_ssl_sync(url):
    if not is_valid_monitoring_url(url):
        return -1
    hostname = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert(True)
                x509_cert = x509.load_der_x509_certificate(cert, default_backend())

                if hasattr(x509_cert, "not_valid_after_utc"):
                    expire_date = x509_cert.not_valid_after_utc
                    now = datetime.now(timezone.utc)
                else:
                    expire_date = x509_cert.not_valid_after
                    now = datetime.utcnow()

                return (expire_date - now).days
    except:
        return -1


async def check_ssl(url):
    return await asyncio.to_thread(_check_ssl_sync, url)

async def check_domain_expiry(url):
    if not is_valid_monitoring_url(url):
        return -1, None, None
    hostname = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
    hostname = hostname.replace("www.", "")
    parts = [p for p in hostname.split(".") if p]
    if len(parts) < 2:
        return -1, None, None

    # Пробуем whois от более полного имени к базовому домену.
    # Пример: a.b.example.com -> b.example.com -> example.com
    candidates = [".".join(parts[i:]) for i in range(0, len(parts) - 1)]

    try:
        for candidate in candidates:
            proc = await asyncio.create_subprocess_exec(
                "whois", candidate,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            text = stdout.decode(errors="ignore")

            # 1. Дата окончания
            match = re.search(
                r"(paid-till|expiry date|expiration date)[\s:]+([0-9T:\-\.Z]+)",
                text, flags=re.IGNORECASE
            )
            date_str = match.group(2).strip() if match else None
            days = -1
            if date_str:
                for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%d-%b-%Y", "%Y.%m.%d"):
                    try:
                        expire = datetime.strptime(date_str, fmt)
                        days = (expire - datetime.utcnow()).days
                        break
                    except:
                        continue

            # 2. Регистратор
            registrar_match = re.search(r"registrar:\s*(.+)", text, re.IGNORECASE)
            registrar = registrar_match.group(1).strip() if registrar_match else "Не найден"

            # 3. Ссылка на контакт/регистратора
            contact_match = re.search(r"(admin-contact|registrar url):\s*(https?://\S+)", text, re.IGNORECASE)
            contact_url = contact_match.group(2).strip() if contact_match else None

            if days >= 0:
                return days, registrar, contact_url

        return -1, None, None

    except Exception as e:
        return -1, None, None


#async def get_geo_info(url: str) -> str:
#    try:
#        hostname = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
#        ip = socket.gethostbyname(hostname)
#
#        # Получим базовую страну через внешнее API (быстро)
#        async with aiohttp.ClientSession() as session:
#            async with session.get(f"https://ipapi.co/{ip}/json/") as resp:
#                data = await resp.json()
#                country = data.get("country_name", "неизвестно")
#                region = data.get("region", "")
#                location = f"{country}, {region}".strip(", ")
#
#        # Получим ASN из whois (может занять 1–2 сек.)
#        obj = IPWhois(ip)
#        res = obj.lookup_rdap(depth=1)
#        asn = res.get("asn", "—")
#        org = res.get("asn_description", "").split(",")[0]
#
#        return f"🌐 IP: {ip}\n📍 Местоположение: {location}\n🛰️ ASN: {asn} ({org})"
#    except Exception as e:
#        return "⚠️ GeoIP/ASN информация недоступна"
async def get_geo_info(url: str) -> str:
    try:
        hostname = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
        ip = socket.gethostbyname(hostname)

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://ipapi.co/{ip}/json/") as resp:
                data = await resp.json()

        country = data.get("country_name", "неизвестно")
        region = data.get("region", "")
        location = f"{country}, {region}".strip(", ")

        asn = data.get("asn", "—")
        org = data.get("org", "—")

        return f"🌐 IP: {ip}\n📍 Местоположение: {location}\n🛰️  ASN: {asn} ({org})"
    except Exception:
        return "⚠️ GeoIP/ASN информация недоступна"
