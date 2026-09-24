"""Scheduled report delivery and blocked-user cleanup."""

import os

from aiogram.exceptions import TelegramForbiddenError

from bot.infra.db import (
    delete_user_sites, get_latest_agent_results_for_urls, get_report_sites,
    log_event, log_user_action,
)
from bot.core.status_formatter import format_weekly_user_report_chunks, group_rows_by_user


BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))


async def notify_block(bot, user_id, url):
    """Remove blocked users and notify the operator."""
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
    agent_results_by_url = get_latest_agent_results_for_urls(row["url"] for row in rows)
    for row in rows:
        row["agent_results"] = agent_results_by_url.get(row["url"], [])
    grouped = group_rows_by_user(rows)

    for user_id, user_rows in grouped.items():
        try:
            for chunk in format_weekly_user_report_chunks(user_rows):
                await bot.send_message(user_id, chunk)
        except TelegramForbiddenError:
            first_url = user_rows[0]["url"] if user_rows else "weekly_report"
            await notify_block(bot, user_id, first_url)
        except Exception as e:
            log_event("weekly_report", f"Не удалось отправить отчёт пользователю {user_id}: {e}")

    if BOT_OWNER_ID:
        try:
            for chunk in format_weekly_user_report_chunks(rows, title="📅 Еженедельный админ-отчёт по всем ресурсам"):
                await bot.send_message(BOT_OWNER_ID, chunk)
        except Exception as e:
            log_event("weekly_report", f"Не удалось отправить админ-отчёт: {e}")
