import asyncio
import os
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from agent.config import AgentConfig
from agent.protocol import utc_now_iso


def resolve_hostname(url: str):
    hostname = urlparse(url).hostname
    if not hostname:
        return None
    try:
        return socket.gethostbyname(hostname)
    except socket.error:
        return None


async def check_http_details(url: str, retries: int = 3, delay: int = 5) -> dict:
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WebcheckAgent/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }

    allow_http_fallback = os.getenv("HTTP_ALLOW_PLAIN_FALLBACK", "1") == "1"
    resolved_ip = resolve_hostname(url)
    urls_to_try = [url]
    if allow_http_fallback and url.startswith("https://"):
        urls_to_try.append("http://" + url[len("https://"):])

    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    last_error = None
    attempts = 0
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
        connector=connector,
        max_field_size=65536,
    ) as session:
        for attempt in range(1, retries + 1):
            for current_url in urls_to_try:
                try:
                    for method in ("HEAD", "GET"):
                        attempts += 1
                        started = time.monotonic()
                        async with session.request(method, current_url, allow_redirects=False) as resp:
                            latency_ms = int((time.monotonic() - started) * 1000)
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
                                }
                            if method == "HEAD":
                                continue
                            last_error = f"HTTP {resp.status}"
                            break
                except Exception as e:
                    last_error = str(e) or type(e).__name__

            if attempt < retries:
                await asyncio.sleep(delay * attempt)

    return {
        "ok": False,
        "status_code": None,
        "method": None,
        "url": urls_to_try[-1],
        "latency_ms": None,
        "attempts": attempts,
        "error": last_error or "No successful HTTP response",
        "ip": resolved_ip,
    }


async def check_ssl(url: str) -> int:
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
    except Exception:
        return -1


async def check_domain_expiry(url: str):
    hostname = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
    hostname = hostname.replace("www.", "")
    parts = [p for p in hostname.split(".") if p]
    if len(parts) < 2:
        return -1, None, None

    candidates = [".".join(parts[i:]) for i in range(0, len(parts) - 1)]
    for candidate in candidates:
        try:
            proc = await asyncio.create_subprocess_exec(
                "whois",
                candidate,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            text = stdout.decode(errors="ignore")
        except Exception:
            continue

        match = re.search(
            r"(paid-till|expiry date|expiration date)[\s:]+([0-9T:\-\.Z]+)",
            text,
            flags=re.IGNORECASE,
        )
        date_str = match.group(2).strip() if match else None
        days = -1
        if date_str:
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%d-%b-%Y", "%Y.%m.%d"):
                try:
                    expire = datetime.strptime(date_str, fmt)
                    days = (expire - datetime.utcnow()).days
                    break
                except ValueError:
                    continue

        registrar_match = re.search(r"registrar:\s*(.+)", text, re.IGNORECASE)
        registrar = registrar_match.group(1).strip() if registrar_match else None
        contact_match = re.search(r"(admin-contact|registrar url):\s*(https?://\S+)", text, re.IGNORECASE)
        contact_url = contact_match.group(2).strip() if contact_match else None
        if days >= 0:
            return days, registrar, contact_url

    return -1, None, None


async def run_check(config: AgentConfig, request: dict) -> dict:
    job_id = request.get("job_id")
    url = request.get("url")
    checks = set(request.get("checks") or ["http", "ssl", "domain"])
    if not url:
        raise ValueError("Missing url")

    started = time.monotonic()
    http = await check_http_details(url) if "http" in checks else None
    ssl_days = await check_ssl(url) if "ssl" in checks else None
    if "domain" in checks:
        domain_days, registrar, contact_url = await check_domain_expiry(url)
    else:
        domain_days, registrar, contact_url = None, None, None

    ok = True
    if http is not None:
        ok = bool(http.get("ok"))

    return {
        "type": "check.result",
        "job_id": job_id,
        "agent_id": config.agent_id,
        "country": config.country,
        "region": config.region,
        "provider": config.provider,
        "url": url,
        "ok": ok,
        "http": http,
        "ssl_days": ssl_days,
        "domain_days": domain_days,
        "registrar": registrar,
        "contact_url": contact_url,
        "error": None,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "finished_at": utc_now_iso(),
    }
