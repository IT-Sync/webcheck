from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import (
    add_site, get_sites, delete_site, get_all_sites, get_site_statuses,
    get_event_logs, log_user_action, get_user_logs,
    export_user_logs_csv as export_logs_file,
    export_sites_csv as export_sites_file,
    admin_delete_site, update_site_status, delete_user_data
)
from monitor import check_http, check_ssl, check_domain_expiry, get_geo_info
from subfinder import find_subdomains, export_subdomains_csv
import os
import asyncio
import socket
from urllib.parse import urlparse

router = Router()
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

def normalize_url(url: str) -> str:
    url = url.strip().lower()
    if not url.startswith("http"):
        url = "https://" + url
    url = url.replace("www.", "")
    parsed = urlparse(url)
    return f"https://{parsed.hostname}" if parsed.hostname else url

def is_domain_resolvable(domain: str) -> bool:
    try:
        socket.gethostbyname(domain)
        return True
    except socket.error:
        return False

def build_site_keyboard(url):
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статус", callback_data=f"status:{url}")
    kb.button(text="🗑 Удалить", callback_data=f"delete:{url}")
    return kb.as_markup()

async def process_site_input(user_id, username, url, bot):
    url = normalize_url(url)
    
    if url in ["https://127.0.0.1", "https://localhost"]:
        await bot.send_message(user_id, "🖥️ Со мной всегда всё в порядке. Меня не нужно проверять 😎")
        return
    
    domain = urlparse(url).hostname

    if not is_domain_resolvable(domain):
        await bot.send_message(user_id, f"❌ Домен `{domain}` не резолвится. Проверьте правильность имени.", parse_mode="Markdown")
        return

    sites = get_sites(user_id)
    if any(s[3] == url for s in sites):
        await bot.send_message(user_id, "⚠️ Этот сайт уже добавлен.")
        return

    add_site(user_id, url, username)
    log_user_action(user_id, f"Добавил сайт: {url}", username)
    # 👇 Добавляем GeoIP-проверку
    geo_info = await get_geo_info(url)
    await bot.send_message(user_id, geo_info)
    
    await bot.send_message(user_id, f"✅ Добавлен сайт: {url}\nПроверяю...")
    await send_status_report(user_id, url, bot)

@router.message(F.text == "/start")
async def cmd_start(message: types.Message):
    log_user_action(message.from_user.id, "/start", message.from_user.username)
    await message.answer(
        "Привет! Я бот для мониторинга сайтов.\n\n"
        "📡 Просто отправь ссылку на сайт, например:\n"
        "`https://example.com` или `example.com`\n\n"
        "📋 Команды:\n"
        "/list — Мои сайты\n"
        "/delete <URL> — Удалить сайт\n"
        "/statusme — Статус всех сайтов\n"
        "/statusme <URL> — Статус одного сайта\n"
        "/subdomains <домен> — Поиск поддоменов\n\n"
        "🔐 SSL и 🌐 домен также проверяются.\n"
        "_Поддомены не проходят проверку домена._\n\n"
        "🔔 Я пришлю уведомление, если:\n"
        "— сайт станет недоступен\n"
        "— до окончания SSL-сертификата останется 14 дней или меньше\n"
        "— до окончания регистрации домена останется 14 дней или меньше.",
        parse_mode="Markdown"
    )

@router.message(F.text == "/help")
async def cmd_help(message: types.Message):
    log_user_action(message.from_user.id, "/help", message.from_user.username)
    await message.answer(
        "🆘 <b>Помощь по командам</b>\n\n"
        "💡 Просто отправьте ссылку на сайт, и я начну его мониторинг.\n\n"
        "📋 <b>Доступные команды:</b>\n"
        "/list — Показать ваши добавленные сайты\n"
        "/delete &lt;URL&gt; — Удалить сайт из мониторинга\n"
        "/statusme — Проверить статус всех ваших сайтов\n"
        "/statusme &lt;URL&gt; — Проверить статус конкретного сайта\n"
        "/subdomains &lt;домен&gt; — Найти поддомены \n\n"
        "🔐 <b>Я проверяю:</b>\n"
        "— доступность сайта (HTTP)\n"
        "— срок действия SSL-сертификата\n"
        "— дату окончания регистрации домена (кроме поддоменов)\n\n"
        "🔔 <b>Я отправлю уведомление, если:</b>\n"
        "— сайт станет недоступен\n"
        "— SSL или домен истекают через 14 дней или раньше\n\n"
        "✍️ Просто пришлите ссылку — и начнётся мониторинг!",
        parse_mode="HTML"
    )

@router.message(F.text.startswith("/delete"))
async def delete_website(message: types.Message):
    user_id = message.from_user.id
    try:
        url = normalize_url(message.text.split(" ", 1)[1].strip())
        deleted = delete_site(user_id, url)
        log_user_action(user_id, f"Удалил сайт: {url}", message.from_user.username)
        if deleted:
            await message.answer(f"🗑 Удалён сайт: {url}")
        else:
            await message.answer("❌ Сайт не найден среди ваших.")
    except IndexError:
        await message.answer("Используйте: /delete <URL>")

@router.message(F.text == "/list")
async def list_websites(message: types.Message):
    user_id = message.from_user.id
    log_user_action(user_id, "/list", message.from_user.username)
    sites = get_sites(user_id)
    if not sites:
        await message.answer("У вас пока нет добавленных сайтов.")
    else:
        for site in sites:
            await message.answer(
                f"🔗 {site[3]}",
                reply_markup=build_site_keyboard(site[3])
            )

@router.callback_query(F.data.startswith("status:"))
async def inline_status(query: types.CallbackQuery):
    url = normalize_url(query.data.split(":", 1)[1])
    await query.answer("Проверяю...")
    asyncio.create_task(send_status_report(query.from_user.id, url, query.message.bot))

@router.callback_query(F.data.startswith("delete:"))
async def inline_delete(query: types.CallbackQuery):
    url = normalize_url(query.data.split(":", 1)[1])
    deleted = delete_site(query.from_user.id, url)
    log_user_action(query.from_user.id, f"Удалил сайт (inline): {url}", query.from_user.username)
    if deleted:
        await query.message.answer(f"🗑 Удалён сайт: {url}")
    else:
        await query.message.answer("❌ Сайт не найден среди ваших.")
    await query.answer("Удалено.")

#@router.callback_query(F.data.startswith("admindelete_raw:"))
#async def admin_delete_raw(query: types.CallbackQuery):
#    if query.from_user.id != BOT_OWNER_ID:
#        return await query.answer("⛔ Нет доступа", show_alert=True)
#    url = query.data.split(":", 1)[1]
#    admin_delete_site(url)
#    await query.message.answer(f"🗑 Сайт {url} удалён администратором")
#    await query.answer("Удалено.")

@router.callback_query(F.data.startswith("admindelete:"))
async def admin_delete_site_for_user(query: types.CallbackQuery):
    if query.from_user.id != BOT_OWNER_ID:
        return await query.answer("⛔ Нет доступа", show_alert=True)

    try:
        _, user_id_str, url = query.data.split(":", 2)
        user_id = int(user_id_str)
    except ValueError:
        return await query.answer("❌ Неверный формат данных", show_alert=True)

    deleted = delete_site(user_id, url)  # используем общую функцию
    if deleted:
        await query.message.answer(f"🗑 Сайт {url} удалён у пользователя {user_id}")
    else:
        await query.message.answer(f"⚠️ Сайт {url} не найден у пользователя {user_id}")
    await query.answer("Удалено.")

@router.callback_query(F.data.startswith("adminuser:"))
async def admin_user_details(query: types.CallbackQuery):
    if query.from_user.id != BOT_OWNER_ID:
        return await query.answer("⛔ Нет доступа", show_alert=True)

    try:
        user_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверный формат данных", show_alert=True)

    sites = get_sites(user_id)
    if not sites:
        await query.message.answer(f"У пользователя {user_id} нет сайтов.")
        return await query.answer("Нет данных")

    username = next((row[2] for row in sites if row[2]), None)
    total = len(sites)
    chunk_size = 5

    log_user_action(
        query.from_user.id,
        f"/admin view {user_id}",
        query.from_user.username
    )

    for start in range(0, total, chunk_size):
        chunk = sites[start:start + chunk_size]
        lines = []
        kb = InlineKeyboardBuilder()
        for idx, site in enumerate(chunk, start=start + 1):
            url = site[3]
            lines.append(f"{idx}. {url}")
            kb.button(text=f"🗑 {idx}", callback_data=f"admindelete:{user_id}:{url}")
        kb.adjust(2)

        header = f"Пользователь {user_id}"
        if username:
            header += f" (@{username})"
        header += f"\nСайты {start + 1}-{start + len(chunk)} из {total}:"

        await query.message.answer(header + "\n" + "\n".join(lines), reply_markup=kb.as_markup())

    await query.answer("Отправлено")


async def send_status_report(user_id, url, bot):
    http_ok = await check_http(url)
    ssl_days = await check_ssl(url)
    domain_days, registrar, contact_url = await check_domain_expiry(url)

    status_str = f"{'OK' if http_ok else 'DOWN'}, SSL {ssl_days}d, Domain {domain_days}d"
    update_site_status(url, status_str)

    text = f"🔗 {url}\n"
    text += "✅ Сайт доступен\n" if http_ok else "❌ Сайт недоступен\n"
    text += f"🔐 SSL: {ssl_days} дней до истечения\n" if ssl_days >= 0 else "⚠️ SSL не проверен\n"

    if domain_days == -2:
        text += "🌐 Домен: 🔒 Проверка недоступна для поддоменов"
    else:
        if domain_days >= 0:
            text += f"🌐 Домен: {domain_days} дней до окончания\n"
        else:
            text += "⚠️ Домен не проверен\n"

        if registrar:
            text += f"🏢 Регистратор: {registrar}\n"
        if contact_url:
            text += f"🔗 Сайт регистратора: {contact_url}"

    await bot.send_message(user_id, text)

@router.message(F.text.startswith("/statusme"))
async def status_me(message: types.Message):
    log_user_action(message.from_user.id, "/statusme", message.from_user.username)
    args = message.text.split(" ", 1)
    if len(args) == 2:
        url = normalize_url(args[1].strip())
        await message.answer(f"Проверка {url}...")
        await send_status_report(message.from_user.id, url, message.bot)
    else:
        sites = get_sites(message.from_user.id)
        if not sites:
            await message.answer("У вас нет сайтов.")
        for site in sites:
            await send_status_report(message.from_user.id, site[3], message.bot)

@router.message(F.text == "/admin")
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

@router.message(F.text == "/status")
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

@router.message(F.text.startswith("/remove_user"))
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

    sites_deleted, logs_deleted = delete_user_data(target_user_id)

    if sites_deleted == 0 and logs_deleted == 0:
        await message.answer(f"Данные пользователя {target_user_id} не найдены.")
    else:
        await message.answer(
            f"🧹 Пользователь {target_user_id} удалён.\n"
            f"Удалено сайтов: {sites_deleted}\n"
            f"Удалено записей логов: {logs_deleted}"
        )

@router.message(F.text == "/events")
async def admin_events(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    log_user_action(message.from_user.id, "/events", message.from_user.username)
    events = get_event_logs()
    if not events:
        await message.answer("Событий нет за последние 14 дней.")
    else:
        text = "\n".join([f"{ts}: {url} — {msg}" for ts, url, msg in events])
        await message.answer(f"События:\n{text}")

@router.message(F.text == "/logs")
async def admin_user_logs(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    log_user_action(message.from_user.id, "/logs", message.from_user.username)
    logs = get_user_logs()
    if not logs:
        return await message.answer("Нет логов действий за последние 14 дней.")
    lines = [
        f"{ts}: {user_id} (@{username}) — {action}" if username else f"{ts}: {user_id} (без username) — {action}"
        for ts, user_id, username, action in logs
    ]
    chunk_size = 50
    for i in range(0, len(lines), chunk_size):
        part = "\n".join(lines[i:i + chunk_size])
        await message.answer(part)

@router.message(F.text == "/export_logs")
async def export_logs_csv(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    path = export_logs_file()
    await message.answer_document(types.FSInputFile(path), caption="Экспорт логов действий за 14 дней")

@router.message(F.text == "/export_sites")
async def export_sites_csv(message: types.Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.answer("Нет доступа")
    path = export_sites_file()
    await message.answer_document(types.FSInputFile(path), caption="Список сайтов с последним статусом")

#@router.message(F.text.startswith("/subdomains"))
#async def cmd_subdomains(message: types.Message):
#    log_user_action(message.from_user.id, "/subdomains", message.from_user.username)
#    parts = message.text.split(" ", 1)
#    if len(parts) != 2:
#        return await message.answer("Используйте: /subdomains example.com")
#
#    domain = parts[1].strip().lower()
#    await message.answer(f"🔍 Ищу поддомены для `{domain}`...", parse_mode="Markdown")
#
#    subdomains = await find_subdomains(domain)
#
#    if not subdomains:
#        return await message.answer("❌ Поддомены не найдены или произошла ошибка.")
#
#    preview = "\n".join(f"• `{s}`" for s in subdomains[:30])
#    text = f"Найдено {len(subdomains)} поддоменов:\n{preview}"
#    await message.answer(text, parse_mode="Markdown")
@router.message(F.text.startswith("/subdomains"))
async def cmd_subdomains(message: types.Message):
    log_user_action(message.from_user.id, "/subdomains", message.from_user.username)
    parts = message.text.split(" ", 1)
    if len(parts) != 2:
        return await message.answer("Используйте: /subdomains example.com")

    domain = parts[1].strip().lower()
    await message.answer(f"🔍 Ищу поддомены для `{domain}`...", parse_mode="Markdown")

    subdomains = await find_subdomains(domain)

    if not subdomains:
        return await message.answer("❌ Поддомены не найдены или произошла ошибка.")

    if len(subdomains) > 10:
        path = await export_subdomains_csv(subdomains, domain)
        await message.answer_document(types.FSInputFile(path), caption=f"📄 Найдено {len(subdomains)} поддоменов для {domain}")
        os.remove(path)
    else:
        preview = "\n".join(f"• `{s}`" for s in subdomains)
        await message.answer(f"🔍 Найдено {len(subdomains)} поддоменов:\n{preview}", parse_mode="Markdown")


# Обработчик, не мешающий командам
#@router.message(F.text)
#async def universal_add(message: types.Message):
#    text = message.text.strip()
#    if text.startswith("/"):
#        return
#    if "." in text and " " not in text:
#        await process_site_input(
#            message.from_user.id,
#            message.from_user.username,
#            text,
#            message.bot
#        )
#
#def register_handlers(dp, bot):
#    dp.include_router(router)

@router.message(F.text)
async def universal_add(message: types.Message):
    text = message.text.strip()

    # Игнорируем команды (обрабатываются выше)
    if text.startswith("/"):
        return await message.answer(
            "❓ Неизвестная команда. Попробуйте /help для списка доступных.",
            parse_mode="Markdown"
        )

    # Проверка на похожесть на домен
    if "." in text and " " not in text:
        return await process_site_input(
            message.from_user.id,
            message.from_user.username,
            text,
            message.bot
        )

    # Всё остальное — как непонятный текст
    await message.answer(
        "🤔 Я не понял это сообщение.\n\n"
        "📘 Отправьте ссылку на сайт для мониторинга\n"
        "или используйте /help для списка команд.",
        parse_mode="Markdown"
    )


def register_handlers(dp, bot):
    dp.include_router(router)
