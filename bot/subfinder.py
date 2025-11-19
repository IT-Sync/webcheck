import aiohttp
from bs4 import BeautifulSoup
import re
import csv
import tempfile
import os

async def find_subdomains(domain: str) -> list:
    subdomains = set()

    # --- [1] crt.sh ---
    crt_url = f"https://crt.sh/?q=%25.{domain}&output=json"
    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(crt_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    for entry in data:
                        sub = entry.get("name_value", "")
                        for line in sub.splitlines():
                            if domain in line:
                                subdomains.add(line.strip().lower())
    except Exception as e:
        print(f"[crt.sh] Ошибка: {e}")

    # --- [2] DNSdumpster ---
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://dnsdumpster.com"
            }

            async with session.get("https://dnsdumpster.com", headers=headers) as resp:
                html = await resp.text()
                token_match = re.search(r'name="csrfmiddlewaretoken" value="(.+?)"', html)
                token = token_match.group(1) if token_match else None

            if not token:
                print("[dnsdumpster] Не удалось получить токен")
                return list(subdomains)

            data = {"csrfmiddlewaretoken": token, "targetip": domain}
            cookies = {"csrftoken": token}

            async with session.post("https://dnsdumpster.com", data=data, headers=headers, cookies=cookies) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")
                table = soup.find("table", class_="table table-bordered table-hover")
                if table:
                    rows = table.find_all("tr")
                    for row in rows:
                        cols = row.find_all("td")
                        if cols and len(cols) > 0:
                            host = cols[0].text.strip()
                            if domain in host:
                                subdomains.add(host.lower())
    except Exception as e:
        print(f"[dnsdumpster] Ошибка: {e}")

    return sorted(subdomains)


async def export_subdomains_csv(subdomains: list, domain: str) -> str:
    """Создаёт временный CSV-файл со списком поддоменов и возвращает путь к нему"""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix=f"subdomains_{domain}_")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Subdomain"])
        for sub in subdomains:
            writer.writerow([sub])
    return path

