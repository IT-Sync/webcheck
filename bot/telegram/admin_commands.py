"""Owner-only Telegram commands and their router registration."""

import os

from aiogram import F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.infra.db import (
    delete_user_data, export_sites_csv as export_sites_file,
    export_user_logs_csv as export_logs_file, get_all_sites, get_event_logs,
    get_latest_agent_results_for_urls, get_report_sites, get_site_statuses,
    get_user_logs, log_user_action,
)
from bot.core.status_formatter import format_weekly_user_report_chunks


BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

ADMIN_COMMANDS_TEXT = (
    "🛠 Админ-команды:\n"
    "/admin_help — список админских команд\n"
    "/admin — пользователи и их сайты\n"
    "/admin_stats — статистика по пользователям\n"
    "/status — статусы всех сайтов\n"
    "/events — журнал событий за 14 дней\n"
    "/logs — действия пользователей за 14 дней\n"
    "/export_logs — экспорт логов CSV\n"
    "/export_sites — экспорт сайтов CSV\n"
    "/weekly_all — еженедельный отчёт по всем ресурсам\n"
    "/remove_user <user_id> — удалить сайты и логи пользователя"
)


async def admin_overview(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    log_user_action(message.from_user.id, "/admin", message.from_user.username)
    all_sites = get_all_sites(full=True)
    if not all_sites:
        return await message.answer("Нет зарегистрированных сайтов.")

    users = {}
    for user_id, url, username in all_sites:
        entry = users.setdefault(user_id, {"username": username, "sites": []})
        if username and not entry["username"]:
            entry["username"] = username
        entry["sites"].append(url)

    sorted_users = sorted(users.items(), key=lambda item: item[0])
    chunk_size = 10

    await message.answer("Выберите пользователя, чтобы посмотреть сайты и удалить их при необходимости.")

    for i in range(0, len(sorted_users), chunk_size):
        chunk = sorted_users[i:i + chunk_size]
        lines = []
        kb = InlineKeyboardBuilder()
        for user_id, data in chunk:
            username = data["username"]
            username_text = f"@{username}" if username else "без username"
            lines.append(f"{user_id}: {len(data['sites'])} сайтов — {username_text}")
            kb.button(text=f"👤 {user_id}", callback_data=f"adminuser:{user_id}")
        kb.adjust(2)
        text = "Пользователи:\n" + "\n".join(lines)
        await message.answer(text, reply_markup=kb.as_markup())

async def admin_help(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    log_user_action(message.from_user.id, "/admin_help", message.from_user.username)
    await message.answer(ADMIN_COMMANDS_TEXT)

async def admin_user_stats(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")

    log_user_action(message.from_user.id, "/admin_stats", message.from_user.username)
    all_sites = get_all_sites(full=True)
    logs = get_user_logs()

    if not all_sites:
        return await message.answer("Нет данных по сайтам.")

    users = {}
    users_with_username = set()
    for user_id, url, username in all_sites:
        entry = users.setdefault(user_id, {"sites": [], "username": None})
        entry["sites"].append(url)
        if username and not entry["username"]:
            entry["username"] = username
        if username:
            users_with_username.add(user_id)

    user_count = len(users)
    site_count = len(all_sites)
    avg_sites = site_count / user_count if user_count else 0
    max_sites = max(len(data["sites"]) for data in users.values()) if users else 0
    users_without_username = user_count - len(users_with_username)

    active_users_14d = len({user_id for _, user_id, _, _ in logs})
    top_users = sorted(users.items(), key=lambda item: len(item[1]["sites"]), reverse=True)[:10]

    top_lines = []
    for idx, (user_id, data) in enumerate(top_users, start=1):
        username = f" (@{data['username']})" if data["username"] else ""
        top_lines.append(f"{idx}. {user_id}{username} — {len(data['sites'])} сайтов")

    text = (
        "📊 Статистика пользователей:\n"
        f"Пользователей с сайтами: {user_count}\n"
        f"Всего сайтов: {site_count}\n"
        f"Среднее сайтов на пользователя: {avg_sites:.2f}\n"
        f"Максимум сайтов у одного пользователя: {max_sites}\n"
        f"Пользователей без username: {users_without_username}\n"
        f"Активных пользователей за 14 дней: {active_users_14d}\n\n"
        "Топ-10 пользователей по числу сайтов:\n"
        + ("\n".join(top_lines) if top_lines else "нет данных")
    )
    await message.answer(text)

async def weekly_admin_report(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    log_user_action(message.from_user.id, "/weekly_all", message.from_user.username)
    rows = get_report_sites()
    agent_results_by_url = get_latest_agent_results_for_urls(row["url"] for row in rows)
    for row in rows:
        row["agent_results"] = agent_results_by_url.get(row["url"], [])
    for chunk in format_weekly_user_report_chunks(rows, title="📅 Еженедельный админ-отчёт по всем ресурсам"):
        await message.answer(chunk)

async def admin_status(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")

    log_user_action(message.from_user.id, "/status", message.from_user.username)
    statuses = get_site_statuses()
    all_sites = get_all_sites(full=True)

    if not statuses or not all_sites:
        return await message.answer("Нет данных для отображения.")

    status_map = {url: status for url, status in statuses}

    lines = []
    for user_id, url, username in all_sites:
        status = status_map.get(url, "Нет данных")
        user_info = f"{user_id} (@{username})" if username else f"{user_id} (без username)"
        lines.append(f"{url}: {status} — {user_info}")

    await message.answer("Статусы сайтов:\n" + "\n".join(lines))

async def admin_remove_user(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")

    parts = message.text.split(maxsplit=1)

    if len(parts) != 2:
        return await message.answer("Используйте: /remove_user <user_id>")

    try:
        target_user_id = int(parts[1].strip())
    except ValueError:
        return await message.answer("ID пользователя должен быть числом.")

    log_user_action(
        message.from_user.id,
        f"/remove_user {target_user_id}",
        message.from_user.username
    )

    try:
        sites_deleted, logs_deleted, messages_deleted = delete_user_data(target_user_id)
    except ValueError as exc:
        if str(exc) != "owned_projects_have_members":
            raise
        return await message.answer("У пользователя есть проекты с участниками. Сначала перенесите права или удалите участников.")

    if sites_deleted == 0 and logs_deleted == 0 and messages_deleted == 0:
        await message.answer(f"Данные пользователя {target_user_id} не найдены.")
    else:
        await message.answer(
            f"🧹 Пользователь {target_user_id} удалён.\n"
            f"Удалено сайтов: {sites_deleted}\n"
            f"Удалено записей логов: {logs_deleted}\n"
            f"Удалено записей сообщений: {messages_deleted}"
        )

async def admin_events(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    log_user_action(message.from_user.id, "/events", message.from_user.username)
    events = get_event_logs()
    if not events:
        await message.answer("Событий нет за последние 14 дней.")
    else:
        lines = [f"{ts}: {url} — {msg}" for ts, url, msg in events]
        max_len = 3500
        chunk = "События:\n"
        for line in lines:
            candidate = f"{chunk}{line}\n"
            if len(candidate) > max_len:
                await message.answer(chunk.rstrip())
                chunk = f"{line}\n"
            else:
                chunk = candidate
        if chunk.strip():
            await message.answer(chunk.rstrip())

async def admin_user_logs(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    logs = get_user_logs()
    log_user_action(message.from_user.id, "/logs", message.from_user.username)
    if not logs:
        return await message.answer("Нет логов действий за последние 14 дней.")

    unique_users = len({user_id for _, user_id, _, _ in logs})
    await message.answer(
        "Логи действий всех пользователей за последние 14 дней:\n"
        f"Записей: {len(logs)}\n"
        f"Пользователей: {unique_users}"
    )

    lines = [
        f"{ts}: {user_id} (@{username}) — {action}" if username else f"{ts}: {user_id} (без username) — {action}"
        for ts, user_id, username, action in logs
    ]
    chunk_size = 50
    for i in range(0, len(lines), chunk_size):
        part = "\n".join(lines[i:i + chunk_size])
        await message.answer(part)

async def export_logs_csv(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    path = export_logs_file()
    await message.answer_document(types.FSInputFile(path), caption="Экспорт логов действий за 14 дней")

async def export_sites_csv(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    path = export_sites_file()
    await message.answer_document(types.FSInputFile(path), caption="Список сайтов с последним статусом")

def register_admin_handlers(router):
    router.message(F.text == "/admin")(admin_overview)
    router.message(F.text == "/admin_help")(admin_help)
    router.message(F.text == "/admin_stats")(admin_user_stats)
    router.message(F.text == "/weekly_all")(weekly_admin_report)
    router.message(F.text == "/status")(admin_status)
    router.message(F.text.startswith("/remove_user"))(admin_remove_user)
    router.message(F.text == "/events")(admin_events)
    router.message(F.text == "/logs")(admin_user_logs)
    router.message(F.text == "/export_logs")(export_logs_csv)
    router.message(F.text == "/export_sites")(export_sites_csv)
