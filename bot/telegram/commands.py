"""Publish supported commands to Telegram's command picker at startup."""

import logging
import os

from aiogram.types import (
    BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat,
    BotCommandScopeDefault,
)


PUBLIC_COMMANDS = (
    ("start", "Начать работу"),
    ("help", "Помощь по командам"),
    ("list", "Мои сайты"),
    ("delete", "Удалить сайт: /delete URL"),
    ("pause", "Приостановить мониторинг: /pause URL"),
    ("resume", "Возобновить мониторинг: /resume URL"),
    ("statusme", "Статусы моих ресурсов: /statusme [URL]"),
    ("weekly", "Отчёт по моим ресурсам"),
    ("app", "Открыть приложение Webcheck"),
    ("feedback", "Написать администратору"),
    ("cancel_feedback", "Отменить отправку обращения"),
    ("subdomains", "Найти поддомены: /subdomains домен"),
)

OWNER_COMMANDS = (
    ("admin_help", "Помощь по админ-командам"),
    ("admin", "Пользователи и их сайты"),
    ("admin_stats", "Статистика пользователей"),
    ("status", "Статусы всех сайтов"),
    ("events", "Журнал событий"),
    ("logs", "Действия пользователей"),
    ("export_logs", "Экспорт логов CSV"),
    ("export_sites", "Экспорт сайтов CSV"),
    ("weekly_all", "Отчёт по всем ресурсам"),
    ("remove_user", "Удалить данные пользователя: /remove_user ID"),
)


async def configure_bot_commands(bot):
    commands = [BotCommand(command=name, description=text)
                for name, text in PUBLIC_COMMANDS]
    scopes = [(BotCommandScopeDefault(), commands),
              (BotCommandScopeAllPrivateChats(), commands)]
    owner_id = int(os.getenv("BOT_OWNER_ID", "0"))
    if owner_id:
        owner_commands = commands + [
            BotCommand(command=name, description=text) for name, text in OWNER_COMMANDS
        ]
        scopes.append((BotCommandScopeChat(chat_id=owner_id), owner_commands))
    for scope, scoped_commands in scopes:
        # Replace both language variants so a stale Russian menu cannot win.
        for language_code in ("", "ru"):
            try:
                await bot.set_my_commands(
                    scoped_commands, scope=scope, language_code=language_code,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failed to configure Telegram commands for scope %s (%s)",
                    scope.type, language_code or "default",
                )
