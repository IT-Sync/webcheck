from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import (
    get_all_site_checks, get_report_sites, update_site_status_by_id,
    log_event, delete_user_sites, log_user_action, update_site_success,
    start_site_incident, clear_site_incident
)
from db import get_site_flags_by_id, set_site_flags_by_id
from monitor import check_http_details, check_ssl, check_domain_expiry
from status_formatter import (
    format_domain_expiry_alert, format_down_alert, format_recovery_alert,
    format_ssl_expiry_alert, format_status_text, format_weekly_user_report,
    group_rows_by_user, split_message
)
from callback_data import site_check_now_callback, site_history_callback, site_pause_1h_callback
from datetime import datetime
from aiogram.exceptions import TelegramForbiddenError
import os
import asyncio

BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
MAX_CONCURRENT_CHECKS = int(os.getenv("MAX_CONCURRENT_CHECKS", "30"))
HTTP_FAILURE_THRESHOLD = int(os.getenv("HTTP_FAILURE_THRESHOLD", "2"))
WEEKLY_REPORT_DAY = os.getenv("WEEKLY_REPORT_DAY", "mon")
WEEKLY_REPORT_HOUR = int(os.getenv("WEEKLY_REPORT_HOUR", "9"))
WEEKLY_REPORT_MINUTE = int(os.getenv("WEEKLY_REPORT_MINUTE", "0"))
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/Moscow")

async def monitor(bot):
    sites = get_all_site_checks()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    tasks = []
    for row in sites:
        tasks.append(process_site_limited(bot, semaphore, row))
    await asyncio.gather(*tasks)

async def process_site_limited(bot, semaphore, site_row):
    async with semaphore:
        await process_site(bot, site_row)

def build_incident_keyboard(site_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="Проверить сейчас", callback_data=site_check_now_callback(site_id))
    kb.button(text="Пауза 1 час", callback_data=site_pause_1h_callback(site_id))
    kb.button(text="Открыть историю", callback_data=site_history_callback(site_id))
    kb.adjust(1)
    return kb.as_markup()

async def process_site(bot, site_row):
    site_id = site_row[0]
    user_id = site_row[1]
    url = site_row[2]
    incident_started_at = site_row[3]
    last_success_at = site_row[4]
    try:
        http_details = await check_http_details(url)
        http_ok = http_details["ok"]
        ssl_days = await check_ssl(url)

        flags = get_site_flags_by_id(site_id)
        notified_http = flags.get("http", False)
        notified_ssl = flags.get("ssl", False)
        notified_domain = flags.get("domain", False)
        http_fail_count = flags.get("http_fail_count", 0)
        last_ssl_ts = flags.get("ssl_ts")
        last_domain_ts = flags.get("domain_ts")
        last_domain_check_ts = flags.get("domain_check_ts")
        cached_domain_days = flags.get("domain_days_cache")
        cached_registrar = flags.get("domain_registrar_cache")
        cached_contact_url = flags.get("domain_contact_url_cache")
        now = datetime.utcnow()

        should_refresh_domain = (
            last_domain_check_ts is None or
            (now - last_domain_check_ts).total_seconds() >= 24 * 60 * 60 or
            cached_domain_days is None or
            cached_domain_days == -2
        )

        if should_refresh_domain:
            domain_days, registrar, contact_url = await check_domain_expiry(url)
            set_site_flags_by_id(
                site_id,
                domain_check_ts=now,
                domain_days_cache=domain_days,
                domain_registrar_cache=registrar,
                domain_contact_url_cache=contact_url
            )
        else:
            domain_days = cached_domain_days
            registrar = cached_registrar
            contact_url = cached_contact_url

        status = format_status_text(http_details, ssl_days, domain_days, registrar, contact_url)
        update_site_status_by_id(site_id, status)

        issues = []

        # HTTP
        if not http_ok:
            new_fail_count = http_fail_count + 1
            incident_started_at = start_site_incident(site_id, now, http_details.get("ip"))
            if not notified_http and new_fail_count >= HTTP_FAILURE_THRESHOLD:
                issues.append(format_down_alert(
                    url,
                    http_details,
                    new_fail_count,
                    incident_started_at=incident_started_at,
                    last_success_at=last_success_at,
                ))
                reason = http_details.get("error") or "нет успешного ответа"
                log_event(url, f"Сайт недоступен ({new_fail_count} подряд провалов): {reason}")
                set_site_flags_by_id(site_id, http=True, http_fail_count=new_fail_count)
            else:
                set_site_flags_by_id(site_id, http_fail_count=new_fail_count)
        elif http_ok and notified_http:
            try:
                await bot.send_message(
                    user_id,
                    format_recovery_alert(url, http_details, incident_started_at=incident_started_at)
                )
            except TelegramForbiddenError:
                await notify_block(bot, user_id, url)
                return
            log_event(url, "Сайт восстановился")
            clear_site_incident(site_id)
            update_site_success(
                site_id,
                http_status=http_details.get("status_code"),
                latency_ms=http_details.get("latency_ms"),
                resolved_ip=http_details.get("ip")
            )
            set_site_flags_by_id(site_id, http=False, http_fail_count=0)
        else:
            if incident_started_at:
                clear_site_incident(site_id)
            update_site_success(
                site_id,
                http_status=http_details.get("status_code"),
                latency_ms=http_details.get("latency_ms"),
                resolved_ip=http_details.get("ip")
            )
            if http_fail_count:
                set_site_flags_by_id(site_id, http_fail_count=0)

        # SSL
        if 0 <= ssl_days <= 14:
            if (not notified_ssl) or (not last_ssl_ts or (now - last_ssl_ts).days >= 1):
                issues.append(format_ssl_expiry_alert(url, ssl_days))
                log_event(url, f"Сертификат истекает через {ssl_days} дней")
                set_site_flags_by_id(site_id, ssl=True, ssl_ts=now)
        else:
            if notified_ssl:
                try:
                    await bot.send_message(user_id, f"✅ SSL продлён для {url} (осталось {ssl_days} дней)")
                except TelegramForbiddenError:
                    await notify_block(bot, user_id, url)
                    return
                log_event(url, f"SSL продлён ({ssl_days} дней)")
                set_site_flags_by_id(site_id, ssl=False, ssl_ts=None)

        # Domain
        if 0 <= domain_days <= 14:
            if (not notified_domain) or (not last_domain_ts or (now - last_domain_ts).days >= 1):
                issues.append(format_domain_expiry_alert(url, domain_days, registrar, contact_url))
                log_event(url, f"Домен истекает через {domain_days} дней")
                set_site_flags_by_id(site_id, domain=True, domain_ts=now)
        else:
            if notified_domain:
                try:
                    await bot.send_message(user_id, f"✅ Домен продлён для {url} (осталось {domain_days} дней)")
                except TelegramForbiddenError:
                    await notify_block(bot, user_id, url)
                    return
                log_event(url, f"Домен продлён ({domain_days} дней)")
                set_site_flags_by_id(site_id, domain=False, domain_ts=None)

        if issues:
            text = "\n\n".join(issues)
            try:
                await bot.send_message(user_id, text, reply_markup=build_incident_keyboard(site_id))
            except TelegramForbiddenError:
                await notify_block(bot, user_id, url)

    except TelegramForbiddenError:
        await notify_block(bot, user_id, url)
    except Exception as e:
        try:
            await bot.send_message(user_id, f"{url} — ошибка проверки: {e}")
        except TelegramForbiddenError:
            await notify_block(bot, user_id, url)

async def notify_block(bot, user_id, url):
    """Обработка блокировки: очистка сайтов пользователя и уведомление администратора."""
    deleted_sites = delete_user_sites(user_id)
    if deleted_sites > 0:
        log_user_action(user_id, f"Автоудаление сайтов после блокировки бота: {deleted_sites}")
        try:
            await bot.send_message(
                BOT_OWNER_ID,
                (
                    f"⚠️ Пользователь `{user_id}` заблокировал бота.\n"
                    f"Удалено сайтов: {deleted_sites}\n"
                    f"Триггер: {url}"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Не удалось уведомить администратора: {e}")
        log_event(url, f"Пользователь {user_id} заблокировал бота; удалено сайтов: {deleted_sites}")

async def send_weekly_reports(bot):
    rows = get_report_sites()
    grouped = group_rows_by_user(rows)

    for user_id, user_rows in grouped.items():
        try:
            for chunk in split_message(format_weekly_user_report(user_rows)):
                await bot.send_message(user_id, chunk)
        except TelegramForbiddenError:
            first_url = user_rows[0]["url"] if user_rows else "weekly_report"
            await notify_block(bot, user_id, first_url)
        except Exception as e:
            log_event("weekly_report", f"Не удалось отправить отчёт пользователю {user_id}: {e}")

    if BOT_OWNER_ID:
        admin_report = format_weekly_user_report(rows, title="📅 Еженедельный админ-отчёт по всем ресурсам")
        try:
            for chunk in split_message(admin_report):
                await bot.send_message(BOT_OWNER_ID, chunk)
        except Exception as e:
            log_event("weekly_report", f"Не удалось отправить админ-отчёт: {e}")

async def start_scheduler(bot):
    scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
    scheduler.add_job(monitor, "interval", minutes=5, args=[bot])
    scheduler.add_job(
        send_weekly_reports,
        "cron",
        day_of_week=WEEKLY_REPORT_DAY,
        hour=WEEKLY_REPORT_HOUR,
        minute=WEEKLY_REPORT_MINUTE,
        args=[bot],
    )
    scheduler.start()
