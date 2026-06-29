from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = url.replace("www.", "")
    parsed = urlparse(url)
    return f"https://{parsed.hostname}" if parsed.hostname else url
