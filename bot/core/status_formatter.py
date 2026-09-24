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
            parts.append(checked_url)
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


def format_agent_result_line(result):
    agent_id = result.get("agent_id") or "agent"
    country = result.get("country") or "unknown"
    region = result.get("region")
    location = f"{country}, {region}" if region else country
    error = result.get("error")
    http = result.get("http")
    checked_at = result.get("checked_at")
    checked_text = f" · {checked_at.strftime('%H:%M UTC')}" if checked_at else ""
    header = f"• {agent_id} [{location}]{checked_text}"
    if error:
        return f"{header}\n  HTTP: DOWN | {error}"
    if http:
        return f"{header}\n  {format_http_line(http)}"
    status = "OK" if result.get("ok") else "DOWN"
    return f"{header}\n  HTTP: {status}"


def format_agent_results(agent_results):
    if not agent_results:
        return ""
    lines = ["", "🌍 Проверки агентами"]
    lines.extend(format_agent_result_line(result) for result in agent_results)
    return "\n".join(lines)


def format_agent_results_compact(agent_results):
    if not agent_results:
        return ""
    parts = []
    for result in agent_results:
        agent_id = result.get("agent_id") or "agent"
        country = result.get("country") or "unknown"
        region = result.get("region")
        location = f"{country}, {region}" if region else country
        http = result.get("http") or {}
        latency_ms = http.get("latency_ms")
        latency_text = f", {latency_ms} ms" if latency_ms is not None else ""
        status = "OK" if (http.get("ok") or result.get("ok")) else "DOWN"
        if result.get("error"):
            status = f"DOWN: {result['error']}"
        parts.append(f"{agent_id} [{location}]: {status}{latency_text}")
    return "; ".join(parts)


def strip_agent_results(text):
    if not text:
        return text
    marker = "\n🌍 Проверки агентами"
    marker_pos = text.find(marker)
    if marker_pos == -1:
        return text
    return text[:marker_pos].rstrip()


def append_agent_results(text, agent_results):
    agent_text = format_agent_results(agent_results)
    if not agent_text:
        return text
    return f"{strip_agent_results(text)}{agent_text}"


def format_user_status_message(url, http_details, ssl_days, domain_days, registrar=None, contact_url=None, agent_results=None):
    availability = "✅ Сайт доступен" if http_details.get("ok") else "❌ Сайт недоступен"
    text = (
        f"🔗 {url}\n"
        f"{availability}\n"
        f"{format_status_text(http_details, ssl_days, domain_days, registrar, contact_url)}"
    )
    return append_agent_results(text, agent_results)


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


def format_ssl_expiry_alert(url, ssl_days, display_name=None):
    name = display_name or resource_name(url)
    return (
        f"⚠️ SSL истекает через {ssl_days} дней\n\n"
        f"Ресурс: {name}\n"
        f"URL: {url}"
    )


def format_domain_expiry_alert(url, domain_days, registrar=None, contact_url=None, display_name=None):
    name = display_name or resource_name(url)
    lines = [
        f"⚠️ Домен истекает через {domain_days} дней",
        "",
        f"Ресурс: {name}",
        f"URL: {url}",
    ]
    if registrar:
        lines.append(f"Регистратор: {registrar}")
    if contact_url:
        lines.append(f"Сайт регистратора: {contact_url}")
    return "\n".join(lines)


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


def weekly_report_summary_lines(rows, title):
    total = len(rows)
    paused = sum(1 for row in rows if row.get("is_paused") and not row.get("is_maintenance"))
    maintenance = sum(1 for row in rows if row.get("is_maintenance"))
    maintenance_windows = sum(row.get("maintenance_count_7d", 0) for row in rows)
    active = sum(1 for row in rows if not row.get("is_paused") and not row.get("is_maintenance"))
    problems = sum(
        1 for row in rows
        if not row.get("is_paused")
        and not row.get("is_maintenance")
        and status_has_problem(row.get("last_status"))
    )
    expiry = sum(
        1 for row in rows
        if not row.get("is_maintenance")
        and status_has_expiry_warning(row.get("last_status"))
    )

    return [
        title,
        f"Всего ресурсов: {total}",
        f"Активных: {active}",
        f"На паузе: {paused}",
        f"Плановое обслуживание сейчас: {maintenance}",
        f"Плановых окон за 7 дней: {maintenance_windows}",
        f"С проблемами или без актуальной проверки: {problems}",
        f"SSL/домен истекают скоро: {expiry}",
    ]


def format_weekly_resource_lines(rows):
    lines = []
    for row in rows:
        marker = "🛠" if row.get("is_maintenance") else ("⏸" if row.get("is_paused") else ("⚠️" if status_has_problem(row.get("last_status")) else "✅"))
        checked = row.get("last_checked")
        checked_text = checked.strftime("%Y-%m-%d %H:%M") if checked else "не проверялся"
        status = row.get("last_status") or "статус ещё не получен"
        compact_status = " / ".join(strip_agent_results(status).splitlines()[:3])
        compact_agent_results = format_agent_results_compact(row.get("agent_results"))
        lines.append(f"{marker} {row['url']}")
        lines.append(f"   {compact_status}")
        if row.get("maintenance_count_7d"):
            lines.append(f"   Плановых окон за неделю: {row['maintenance_count_7d']}")
        if row.get("is_maintenance"):
            until = row.get("maintenance_ends_at")
            until_text = until.strftime("%Y-%m-%d %H:%M UTC") if until else "нет данных"
            reason = row.get("maintenance_reason") or "без описания"
            lines.append(f"   Плановое обслуживание до {until_text}: {reason}")
        metadata = []
        if row.get("site_group"):
            metadata.append(f"группа: {row['site_group']}")
        if row.get("tags"):
            metadata.append("теги: " + ", ".join(row["tags"]))
        if metadata:
            lines.append("   " + " · ".join(metadata))
        if compact_agent_results:
            lines.append(f"   Агенты: {compact_agent_results}")
        lines.append(f"   Последняя проверка: {checked_text}")
    return lines


def format_weekly_user_report(rows, title="📅 Еженедельный отчёт по ресурсам"):
    lines = weekly_report_summary_lines(rows, title)

    if not rows:
        lines.append("Ресурсов пока нет.")
        return "\n".join(lines)

    lines.append("")
    lines.extend(format_weekly_resource_lines(rows))

    return "\n".join(lines)


def format_weekly_user_report_chunks(rows, title="📅 Еженедельный отчёт по ресурсам", per_message=10):
    if not rows:
        return [format_weekly_user_report(rows, title=title)]

    chunks = []
    total = len(rows)
    total_parts = (total + per_message - 1) // per_message
    for part_index, start in enumerate(range(0, total, per_message), start=1):
        part_rows = rows[start:start + per_message]
        end = start + len(part_rows)
        lines = weekly_report_summary_lines(rows, title)
        if total_parts > 1:
            lines.append(f"Часть {part_index}/{total_parts}: ресурсы {start + 1}-{end} из {total}")
        lines.append("")
        lines.extend(format_weekly_resource_lines(part_rows))
        chunks.append("\n".join(lines))
    return chunks


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
