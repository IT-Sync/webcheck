from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = url.replace("www.", "")
    parsed = urlparse(url)
    return f"https://{parsed.hostname}" if parsed.hostname else url


def is_valid_monitoring_url(value) -> bool:
    """Check stored HTTP(S) target shape without performing DNS or network I/O."""
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlparse(value)
        return (parsed.scheme in ("http", "https") and bool(parsed.hostname)
                and "." in parsed.hostname and parsed.port != 0)
    except ValueError:
        return False
