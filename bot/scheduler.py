from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import get_all_sites, update_site_status, log_event, delete_user_sites, log_user_action
from db import get_site_flags, set_site_flags
from monitor import check_http, check_ssl, check_domain_expiry
from datetime import datetime
from aiogram.exceptions import TelegramForbiddenError
import os
import asyncio

BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
MAX_CONCURRENT_CHECKS = int(os.getenv("MAX_CONCURRENT_CHECKS", "30"))

async def monitor(bot):
    sites = get_all_sites()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    tasks = []
    for user_id, url in sites:
        tasks.append(process_site_limited(bot, semaphore, user_id, url))
    await asyncio.gather(*tasks)

async def process_site_limited(bot, semaphore, user_id, url):
    async with semaphore:
        await process_site(bot, user_id, url)

async def process_site(bot, user_id, url):
    try:
        http_ok = await check_http(url)
        ssl_days = await check_ssl(url)
        domain_days, registrar, contact_url = await check_domain_expiry(url)

        status = f"{'OK' if http_ok else 'DOWN'}, SSL {ssl_days}d, Domain {domain_days}d"
        update_site_status(url, status)

        flags = get_site_flags(url)
        notified_http = flags.get("http", False)
        notified_ssl = flags.get("ssl", False)
        notified_domain = flags.get("domain", False)
        last_ssl_ts = flags.get("ssl_ts")
        last_domain_ts = flags.get("domain_ts")
        now = datetime.utcnow()

        issues = []

        # HTTP
        if not http_ok and not notified_http:
            issues.append("❌ Сайт недоступен")
            log_event(url, "Сайт недоступен")
            set_site_flags(url, http=True)
        elif http_ok and notified_http:
            try:
                await bot.send_message(user_id, f"✅ Сайт снова доступен: {url}")
            except TelegramForbiddenError:
                await notify_block(bot, user_id, url)
                return
            log_event(url, "Сайт восстановился")
            set_site_flags(url, http=False)

        # SSL
        if 0 <= ssl_days <= 14:
            if (not notified_ssl) or (not last_ssl_ts or (now - last_ssl_ts).days >= 1):
                issues.append(f"⚠️ SSL истекает через {ssl_days} дней")
                log_event(url, f"Сертификат истекает через {ssl_days} дней")
                set_site_flags(url, ssl=True, ssl_ts=now)
        else:
            if notified_ssl:
                try:
                    await bot.send_message(user_id, f"✅ SSL продлён для {url} (осталось {ssl_days} дней)")
                except TelegramForbiddenError:
                    await notify_block(bot, user_id, url)
                    return
                log_event(url, f"SSL продлён ({ssl_days} дней)")
                set_site_flags(url, ssl=False, ssl_ts=None)

        # Domain
        if 0 <= domain_days <= 14:
            if (not notified_domain) or (not last_domain_ts or (now - last_domain_ts).days >= 1):
                issues.append(f"⚠️ Домен истекает через {domain_days} дней")
                log_event(url, f"Домен истекает через {domain_days} дней")
                set_site_flags(url, domain=True, domain_ts=now)
        else:
            if notified_domain:
                try:
                    await bot.send_message(user_id, f"✅ Домен продлён для {url} (осталось {domain_days} дней)")
                except TelegramForbiddenError:
                    await notify_block(bot, user_id, url)
                    return
                log_event(url, f"Домен продлён ({domain_days} дней)")
                set_site_flags(url, domain=False, domain_ts=None)

        if issues:
            text = f"🔗 {url}\n" + "\n".join(issues)
            try:
                await bot.send_message(user_id, text)
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

async def start_scheduler(bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(monitor, "interval", minutes=5, args=[bot])
    scheduler.start()
