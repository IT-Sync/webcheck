import aiohttp
import ssl
import socket
import asyncio
import re
import json
import os
from ipwhois import IPWhois
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.backends import default_backend

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

async def check_http(url, retries=3, delay=5):
    timeout = aiohttp.ClientTimeout(total=12)
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
    urls_to_try = [url]
    if allow_http_fallback and url.startswith("https://"):
        urls_to_try.append("http://" + url[len("https://"):])

    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
        connector=connector,
        max_field_size=65536
    ) as session:
        for attempt in range(1, retries + 1):
            for current_url in urls_to_try:
                try:
                    for method in ("HEAD", "GET"):
                        async with session.request(method, current_url, allow_redirects=False) as resp:
                            print(f"[Attempt {attempt}] {method} {resp.status} for {current_url}")
                            # 4xx означает, что сервер отвечает, но может блокировать ботов/доступ.
                            # Для мониторинга доступности это считаем "сайт жив".
                            if 200 <= resp.status < 500:
                                return True

                            # Если HEAD не дал положительный ответ, пробуем GET.
                            if method == "HEAD":
                                continue
                            break
                except Exception as e:
                    error_text = str(e)
                    if "Header value is too long" in error_text:
                        return True
                    print(f"[Attempt {attempt}] Error checking {current_url}: {error_text or type(e).__name__}")

            await asyncio.sleep(delay * attempt)

    return False


async def check_ssl(url):
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

async def check_domain_expiry(url):
    hostname = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
    hostname = hostname.replace("www.", "")
    parts = hostname.split(".")
    if len(parts) > 2:
        return -2, None, None  # Поддомен — не проверяем

    try:
        proc = await asyncio.create_subprocess_exec(
            "whois", hostname,
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

        return days, registrar, contact_url

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
