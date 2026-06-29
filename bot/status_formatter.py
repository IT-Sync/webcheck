from collections import defaultdict
from datetime import datetime


def format_time(ts):
    if not ts:
        return "нет данных"
    return ts.strftime("%H:%M UTC")


def format_duration(started_at, ended_at=None):
    if not started_at:
        return "нет данных"
    ended_at = ended_at or datetime.utcnow()
    total_seconds = max(0, int((ended_at - started_at).total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes} мин {seconds} сек"
    if minutes:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"


def resource_name(url):
    clean = url.replace("https://", "").replace("http://", "").strip("/")
    return clean.split("/", 1)[0] or url


def format_http_line(http_details):
    if http_details.get("ok"):
        status_code = http_details.get("status_code")
        method = http_details.get("method") or "HTTP"
        latency_ms = http_details.get("latency_ms")
        checked_url = http_details.get("url")
        parts = ["HTTP: OK"]
        if status_code:
            parts.append(str(status_code))
        if method:
            parts.append(method)
        if latency_ms is not None:
            parts.append(f"{latency_ms} ms")
        if checked_url:
            parts.append(f"через {checked_url}")
        return " | ".join(parts)

    error = http_details.get("error") or "нет успешного ответа"
    attempts = http_details.get("attempts")
    attempts_text = f", попыток: {attempts}" if attempts else ""
    return f"HTTP: DOWN | причина: {error}{attempts_text}"


def format_ssl_line(ssl_days):
    if ssl_days >= 0:
        return f"SSL: {ssl_days} дней до истечения"
    return "SSL: не проверен"


def format_domain_line(domain_days, registrar=None, contact_url=None):
    if domain_days == -2:
        return "Домен: проверка недоступна для поддоменов"
    if domain_days >= 0:
        line = f"Домен: {domain_days} дней до окончания"
    else:
        line = "Домен: не проверен"
    if registrar:
        line += f"\nРегистратор: {registrar}"
    if contact_url:
        line += f"\nСайт регистратора: {contact_url}"
    return line


def format_status_text(http_details, ssl_days, domain_days, registrar=None, contact_url=None):
    return "\n".join([
        format_http_line(http_details),
        format_ssl_line(ssl_days),
        format_domain_line(domain_days, registrar, contact_url),
    ])


def format_user_status_message(url, http_details, ssl_days, domain_days, registrar=None, contact_url=None):
    availability = "✅ Сайт доступен" if http_details.get("ok") else "❌ Сайт недоступен"
    return (
        f"🔗 {url}\n"
        f"{availability}\n"
        f"{format_status_text(http_details, ssl_days, domain_days, registrar, contact_url)}"
    )


def format_down_alert(
    url,
    http_details,
    fail_count,
    incident_started_at=None,
    last_success_at=None,
    display_name=None,
):
    error = http_details.get("error") or "нет успешного ответа"
    checked_url = http_details.get("url") or url
    ip = http_details.get("ip") or "не определён"
    name = display_name or resource_name(url)
    return (
        f"🚨 {name} недоступен\n\n"
        f"URL: {checked_url}\n"
        f"Причина: {error}\n"
        f"Проверок подряд: {fail_count}\n"
        f"Начало инцидента: {format_time(incident_started_at)}\n"
        f"Последний успешный ответ: {format_time(last_success_at)}\n"
        f"IP: {ip}"
    )


def format_recovery_alert(url, http_details, incident_started_at=None, display_name=None):
    name = display_name or resource_name(url)
    status_code = http_details.get("status_code") or "нет данных"
    latency_ms = http_details.get("latency_ms")
    latency_text = f"{latency_ms} мс" if latency_ms is not None else "нет данных"
    return (
        f"✅ {name} восстановлен\n\n"
        f"Простой: {format_duration(incident_started_at)}\n"
        f"HTTP: {status_code}\n"
        f"Время ответа: {latency_text}"
    )


def status_has_problem(status):
    if not status:
        return True
    normalized = status.upper()
    return "DOWN" in normalized or "SSL: НЕ ПРОВЕРЕН" in normalized or "ДОМЕН: НЕ ПРОВЕРЕН" in normalized


def status_has_expiry_warning(status):
    if not status:
        return False
    for line in status.splitlines():
        if ("SSL:" in line or "Домен:" in line) and "дней" in line:
            numbers = [int(part) for part in line.replace(",", " ").split() if part.isdigit()]
            if numbers and numbers[0] <= 14:
                return True
    return False


def format_weekly_user_report(rows, title="📅 Еженедельный отчёт по ресурсам"):
    total = len(rows)
    paused = sum(1 for row in rows if row.get("is_paused"))
    problems = sum(1 for row in rows if status_has_problem(row.get("last_status")))
    expiry = sum(1 for row in rows if status_has_expiry_warning(row.get("last_status")))

    lines = [
        title,
        f"Всего ресурсов: {total}",
        f"Активных: {total - paused}",
        f"На паузе: {paused}",
        f"С проблемами или без актуальной проверки: {problems}",
        f"SSL/домен истекают скоро: {expiry}",
    ]

    if not rows:
        lines.append("Ресурсов пока нет.")
        return "\n".join(lines)

    lines.append("")
    for row in rows:
        marker = "⏸" if row.get("is_paused") else ("⚠️" if status_has_problem(row.get("last_status")) else "✅")
        checked = row.get("last_checked")
        checked_text = checked.strftime("%Y-%m-%d %H:%M") if checked else "не проверялся"
        status = row.get("last_status") or "статус ещё не получен"
        compact_status = " / ".join(status.splitlines()[:3])
        lines.append(f"{marker} {row['url']}")
        lines.append(f"   {compact_status}")
        lines.append(f"   Последняя проверка: {checked_text}")

    return "\n".join(lines)


def group_rows_by_user(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["user_id"]].append(row)
    return grouped


def split_message(text, max_len=3500):
    chunks = []
    current = ""
    for line in text.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]
