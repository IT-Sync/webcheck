from aiogram import Router, types, F
from aiogram.filters import BaseFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.infra.db import (
    add_site, get_sites, delete_site, get_all_sites, get_site_statuses,
    get_sites_with_pause, get_site_by_url_for_user,
    get_event_logs, log_user_action, get_user_logs,
    get_report_sites, get_event_logs_for_url,
    export_user_logs_csv as export_logs_file,
    export_sites_csv as export_sites_file,
    get_latest_agent_results_for_url, get_latest_agent_results_for_urls,
    update_site_status, update_site_status_by_id, delete_user_data,
    get_site_for_user, get_site_by_id, delete_site_by_id,
    admin_delete_site_by_id, set_site_paused_by_id, set_site_paused,
    get_site_pause_status, create_maintenance_window,
    add_user_feedback_message, cancel_feedback_waiting,
    is_feedback_waiting, start_feedback_waiting
)
from bot.agent_server.checks import check_with_agents
from bot.checks.monitor import get_geo_info
from bot.checks.service import check_resource
from bot.checks.subfinder import find_subdomains, export_subdomains_csv
from bot.telegram.admin_commands import (
    ADMIN_COMMANDS_TEXT, admin_overview, admin_help, admin_user_stats,
    weekly_admin_report, admin_status, admin_remove_user, admin_events,
    admin_user_logs, export_logs_csv, export_sites_csv, register_admin_handlers,
)
from bot.telegram.callback_data import (
    admin_delete_callback, site_delete_callback, site_pause_callback,
    site_resume_callback, site_status_callback, site_check_now_callback,
    site_history_callback, site_pause_1h_callback
)
from bot.core.status_formatter import (
    append_agent_results, format_status_text, format_user_status_message,
    format_weekly_user_report_chunks, split_message
)
from bot.core.url_utils import normalize_url
import os
import asyncio
import socket
from datetime import datetime, timedelta
from urllib.parse import urlparse

router = Router()
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()

class FeedbackPendingFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        text = message.text or message.caption or ""
        attachment = feedback_attachment(message)
        return bool(
            message.from_user
            and (text or attachment)
            and not (message.text or "").startswith("/")
            and is_feedback_waiting(
                message.from_user.id,
                media_group_id=message.media_group_id,
            )
        )


def feedback_attachment(message: types.Message):
    if message.photo:
        file = message.photo[-1]
        return {
            "media_type": "photo",
            "telegram_file_id": file.file_id,
            "telegram_file_unique_id": file.file_unique_id,
            "file_name": "photo.jpg",
            "mime_type": "image/jpeg",
            "file_size": file.file_size,
        }
    candidates = (
        ("animation", message.animation, "animation.mp4", "video/mp4"),
        ("video", message.video, "video.mp4", "video/mp4"),
        ("video_note", message.video_note, "video-note.mp4", "video/mp4"),
        ("document", message.document, "document", "application/octet-stream"),
        ("audio", message.audio, "audio.mp3", "audio/mpeg"),
        ("voice", message.voice, "voice.ogg", "audio/ogg"),
    )
    for media_type, file, default_name, default_mime in candidates:
        if file:
            return {
                "media_type": media_type,
                "telegram_file_id": file.file_id,
                "telegram_file_unique_id": file.file_unique_id,
                "file_name": getattr(file, "file_name", None) or default_name,
                "mime_type": getattr(file, "mime_type", None) or default_mime,
                "file_size": file.file_size,
            }
    return None

def is_domain_resolvable(domain: str) -> bool:
    try:
        socket.gethostbyname(domain)
        return True
    except socket.error:
        return False

def build_site_keyboard(url, site_id=None, paused=False):
    kb = InlineKeyboardBuilder()
    if site_id:
        kb.button(text="📊 Статус", callback_data=site_status_callback(site_id))
        kb.button(text="🔄 Проверить", callback_data=site_check_now_callback(site_id))
        if paused:
            kb.button(text="▶️ Возобновить", callback_data=site_resume_callback(site_id))
        else:
            kb.button(text="⏸ Пауза", callback_data=site_pause_callback(site_id))
        kb.button(text="🗑 Удалить", callback_data=site_delete_callback(site_id))
    else:
        kb.button(text="📊 Статус", callback_data=f"status:{url}")
        kb.button(text="🗑 Удалить", callback_data=f"delete:{url}")
    return kb.as_markup()


def build_web_app_keyboard():
    if not WEB_APP_URL:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="Открыть Webcheck", web_app=types.WebAppInfo(url=WEB_APP_URL))
    return kb.as_markup()

def format_cached_status(site_row, paused=None):
    url = site_row[3]
    status = site_row[4] or "Статус ещё не получен. Нажмите 🔄 Проверить для живой проверки."
    checked_at = site_row[5]
    checked_text = checked_at.strftime("%Y-%m-%d %H:%M:%S") if checked_at else "не проверялся"
    if paused is None:
        paused = False
    pause_text = "\n⏸ Мониторинг на паузе" if paused else ""
    return f"🔗 {url}\n{status}\n🕒 Последняя проверка: {checked_text}{pause_text}"

def build_incident_keyboard(site_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="Проверить сейчас", callback_data=site_check_now_callback(site_id))
    kb.button(text="Пауза 1 час", callback_data=site_pause_1h_callback(site_id))
    kb.button(text="Открыть историю", callback_data=site_history_callback(site_id))
    kb.adjust(1)
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

    site_id = add_site(user_id, url, username)
    log_user_action(user_id, f"Добавил сайт: {url}", username)
    # 👇 Добавляем GeoIP-проверку
    geo_info = await get_geo_info(url)
    await bot.send_message(user_id, geo_info)
    
    await bot.send_message(user_id, f"✅ Добавлен сайт: {url}\nПроверяю...")
    await send_status_report(user_id, url, bot, site_id=site_id)

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
        "/pause <URL> — Поставить мониторинг на паузу\n"
        "/resume <URL> — Возобновить мониторинг\n"
        "/statusme — Сводный отчёт по вашим ресурсам\n"
        "/statusme <URL> — Статус одного сайта\n"
        "/weekly — То же, что /statusme\n"
        "/feedback — Написать администратору\n"
        "/subdomains <домен> — Поиск поддоменов\n\n"
        "🔐 SSL и 🌐 домен также проверяются.\n"
        "_Поддомены не проходят проверку домена._\n\n"
        "🔔 Я пришлю уведомление, если:\n"
        "— сайт станет недоступен\n"
        "— до окончания SSL-сертификата останется 14 дней или меньше\n"
        "— до окончания регистрации домена останется 14 дней или меньше.",
        parse_mode="Markdown",
        reply_markup=build_web_app_keyboard(),
    )


@router.message(F.text == "/app")
async def cmd_app(message: types.Message):
    log_user_action(message.from_user.id, "/app", message.from_user.username)
    keyboard = build_web_app_keyboard()
    if not keyboard:
        return await message.answer("Web-приложение пока не настроено.")
    await message.answer(
        "Откройте панель мониторинга, чтобы управлять своими сайтами.",
        reply_markup=keyboard,
    )


@router.message(F.text == "/feedback")
async def cmd_feedback(message: types.Message):
    try:
        start_feedback_waiting(message.from_user.id, message.from_user.username)
    except Exception as exc:
        print(f"Failed to start feedback: {type(exc).__name__}: {exc}")
        return await message.answer("Обратная связь временно недоступна. Попробуйте позже.")
    log_user_action(message.from_user.id, "/feedback", message.from_user.username)
    await message.answer(
        "💬 Отправьте ваш вопрос, пожелание или описание проблемы. "
        "Можно приложить фото, видео, документ, аудио или голосовое сообщение.\n\n"
        "Следующее сообщение будет отправлено администратору. "
        "Чтобы отменить отправку, используйте /cancel_feedback."
    )


@router.message(F.text == "/cancel_feedback")
async def cmd_cancel_feedback(message: types.Message):
    cancelled = cancel_feedback_waiting(message.from_user.id)
    if cancelled:
        await message.answer("Отправка сообщения администратору отменена.")
    else:
        await message.answer("Сейчас бот не ожидает сообщение для администратора.")

@router.message(F.text == "/help")
async def cmd_help(message: types.Message):
    log_user_action(message.from_user.id, "/help", message.from_user.username)
    await message.answer(
        "🆘 <b>Помощь по командам</b>\n\n"
        "💡 Просто отправьте ссылку на сайт, и я начну его мониторинг.\n\n"
        "📋 <b>Доступные команды:</b>\n"
        "/list — Показать ваши добавленные сайты\n"
        "/delete &lt;URL&gt; — Удалить сайт из мониторинга\n"
        "/pause &lt;URL&gt; — Поставить мониторинг сайта на паузу\n"
        "/resume &lt;URL&gt; — Возобновить мониторинг сайта\n"
        "/statusme — Сводный отчёт по вашим ресурсам\n"
        "/statusme &lt;URL&gt; — Проверить статус конкретного сайта\n"
        "/weekly — То же, что /statusme\n"
        "/app — Открыть web-приложение\n"
        "/feedback — Написать администратору\n"
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

@router.message(F.text.startswith("/pause"))
async def pause_website(message: types.Message):
    user_id = message.from_user.id
    try:
        url = normalize_url(message.text.split(" ", 1)[1].strip())
    except IndexError:
        return await message.answer("Используйте: /pause <URL>")

    updated = set_site_paused(user_id, url, True)
    if updated:
        site = get_site_by_url_for_user(user_id, url)
        log_user_action(user_id, f"Поставил сайт на паузу: {url}", message.from_user.username)
        await message.answer(
            f"⏸ Мониторинг поставлен на паузу: {url}",
            reply_markup=build_site_keyboard(url, site[0], paused=True) if site else None
        )
    else:
        await message.answer("❌ Сайт не найден среди ваших.")

@router.message(F.text.startswith("/resume"))
async def resume_website(message: types.Message):
    user_id = message.from_user.id
    try:
        url = normalize_url(message.text.split(" ", 1)[1].strip())
    except IndexError:
        return await message.answer("Используйте: /resume <URL>")

    updated = set_site_paused(user_id, url, False)
    if updated:
        site = get_site_by_url_for_user(user_id, url)
        log_user_action(user_id, f"Возобновил мониторинг сайта: {url}", message.from_user.username)
        await message.answer(
            f"▶️ Мониторинг возобновлён: {url}",
            reply_markup=build_site_keyboard(url, site[0], paused=False) if site else None
        )
    else:
        await message.answer("❌ Сайт не найден среди ваших.")

@router.message(F.text == "/list")
async def list_websites(message: types.Message):
    user_id = message.from_user.id
    log_user_action(user_id, "/list", message.from_user.username)
    sites = get_sites_with_pause(user_id)
    if not sites:
        await message.answer("У вас пока нет добавленных сайтов.")
    else:
        for site in sites:
            paused = bool(site[6])
            status_text = " ⏸ на паузе" if paused else ""
            await message.answer(
                f"🔗 {site[3]}{status_text}",
                reply_markup=build_site_keyboard(site[3], site[0], paused=paused)
            )

@router.callback_query(F.data.startswith("st:"))
async def inline_status_by_id(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    await query.answer("Готово")
    await query.message.answer(
        format_cached_status(site, paused=get_site_pause_status(site_id)),
        reply_markup=build_site_keyboard(site[3], site_id, paused=get_site_pause_status(site_id))
    )

@router.callback_query(F.data.startswith("status:"))
async def inline_status(query: types.CallbackQuery):
    url = normalize_url(query.data.split(":", 1)[1])
    site = get_site_by_url_for_user(query.from_user.id, url)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)
    await query.answer("Готово")
    await query.message.answer(
        format_cached_status(site, paused=get_site_pause_status(site[0])),
        reply_markup=build_site_keyboard(site[3], site[0], paused=get_site_pause_status(site[0]))
    )

@router.callback_query(F.data.startswith("del:"))
async def inline_delete_by_id(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    deleted = delete_site_by_id(site_id, query.from_user.id)
    log_user_action(query.from_user.id, f"Удалил сайт (inline): {site[3]}", query.from_user.username)
    if deleted:
        await query.message.answer(f"🗑 Удалён сайт: {site[3]}")
    else:
        await query.message.answer("❌ Сайт не найден среди ваших.")
    await query.answer("Удалено.")

@router.callback_query(F.data.startswith("pause:"))
async def inline_pause_by_id(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    set_site_paused_by_id(site_id, query.from_user.id, True)
    log_user_action(query.from_user.id, f"Поставил сайт на паузу (inline): {site[3]}", query.from_user.username)
    await query.message.answer(f"⏸ Мониторинг поставлен на паузу: {site[3]}")
    await query.answer("На паузе")

@router.callback_query(F.data.startswith("resume:"))
async def inline_resume_by_id(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    set_site_paused_by_id(site_id, query.from_user.id, False)
    log_user_action(query.from_user.id, f"Возобновил мониторинг сайта (inline): {site[3]}", query.from_user.username)
    await query.message.answer(f"▶️ Мониторинг возобновлён: {site[3]}")
    await query.answer("Возобновлено")

@router.callback_query(F.data.startswith("chk:"))
async def inline_check_now(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    await query.answer("Проверяю в фоне...")
    await query.message.answer(f"🔄 Запустил живую проверку: {site[3]}")
    asyncio.create_task(send_status_report(query.from_user.id, site[3], query.message.bot, site_id=site_id))

@router.callback_query(F.data.startswith("p1h:"))
async def inline_pause_one_hour(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    paused_until = datetime.utcnow() + timedelta(hours=1)
    try:
        create_maintenance_window(
            site_id, query.from_user.id, datetime.utcnow(), paused_until,
            "Incident alert pause",
        )
    except ValueError:
        return await query.answer(
            "Окно пересекается с уже запланированным", show_alert=True
        )
    log_user_action(query.from_user.id, f"Пауза 1 час из алерта: {site[3]}", query.from_user.username)
    await query.message.answer(
        f"⏸ Мониторинг поставлен на паузу до {paused_until.strftime('%H:%M UTC')}: {site[3]}",
        reply_markup=build_site_keyboard(site[3], site_id, paused=True)
    )
    await query.answer("Пауза включена")

@router.callback_query(F.data.startswith("hist:"))
async def inline_site_history(query: types.CallbackQuery):
    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверные данные", show_alert=True)

    site = get_site_for_user(site_id, query.from_user.id)
    if not site:
        return await query.answer("❌ Сайт не найден", show_alert=True)

    events = get_event_logs_for_url(site[3])
    if not events:
        await query.message.answer(f"Истории событий за 14 дней нет: {site[3]}")
        return await query.answer("История пуста")

    lines = [f"{ts}: {msg}" for ts, _, msg in events[:20]]
    await query.message.answer(f"История {site[3]}:\n" + "\n".join(lines))
    await query.answer("История открыта")

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

@router.callback_query(F.data.startswith("ad:"))
async def admin_delete_site_by_site_id(query: types.CallbackQuery):
    if query.from_user.id != BOT_OWNER_ID:
        return await query.answer("⛔ Нет доступа", show_alert=True)

    try:
        site_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await query.answer("❌ Неверный формат данных", show_alert=True)

    site = get_site_by_id(site_id)
    if not site:
        return await query.answer("Сайт уже удалён", show_alert=True)

    deleted = admin_delete_site_by_id(site_id)
    if deleted:
        await query.message.answer(f"🗑 Сайт {site[3]} удалён у пользователя {site[1]}")
    else:
        await query.message.answer(f"⚠️ Сайт {site[3]} не найден")
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
            kb.button(text=f"🗑 {idx}", callback_data=admin_delete_callback(site[0]))
        kb.adjust(2)

        header = f"Пользователь {user_id}"
        if username:
            header += f" (@{username})"
        header += f"\nСайты {start + 1}-{start + len(chunk)} из {total}:"

        await query.message.answer(header + "\n" + "\n".join(lines), reply_markup=kb.as_markup())

    await query.answer("Отправлено")


async def send_status_report(user_id, url, bot, site_id=None):
    result = await check_resource(url)
    agent_results = await check_with_agents(url, checks=["http", "ssl", "domain"])
    status_str = format_status_text(
        result.http,
        result.ssl_days,
        result.domain_days,
        result.registrar,
        result.contact_url,
    )
    status_str = append_agent_results(status_str, agent_results)
    if site_id:
        update_site_status_by_id(site_id, status_str)
    else:
        update_site_status(url, status_str)

    text = format_user_status_message(
        url,
        result.http,
        result.ssl_days,
        result.domain_days,
        result.registrar,
        result.contact_url,
        agent_results=agent_results,
    )
    await bot.send_message(user_id, text)

@router.message(F.text.startswith("/statusme"))
async def status_me(message: types.Message):
    log_user_action(message.from_user.id, "/statusme", message.from_user.username)
    args = message.text.split(" ", 1)
    user_sites = get_sites_with_pause(message.from_user.id)

    if len(args) == 2:
        url = normalize_url(args[1].strip())
        site = next((s for s in user_sites if s[3] == url), None)
        if not site:
            return await message.answer("❌ Этот сайт не найден среди ваших.")
        agent_results = get_latest_agent_results_for_url(url)
        await message.answer(append_agent_results(format_cached_status(site, paused=site[6]), agent_results))
    else:
        await send_weekly_user_report(message)

async def send_weekly_user_report(message: types.Message):
    rows = get_report_sites(user_id=message.from_user.id)
    agent_results_by_url = get_latest_agent_results_for_urls(row["url"] for row in rows)
    for row in rows:
        row["agent_results"] = agent_results_by_url.get(row["url"], [])
    for chunk in format_weekly_user_report_chunks(rows):
        await message.answer(chunk)

@router.message(F.text == "/weekly")
async def weekly_user_report(message: types.Message):
    log_user_action(message.from_user.id, "/weekly", message.from_user.username)
    await send_weekly_user_report(message)

register_admin_handlers(router)

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


@router.message(FeedbackPendingFilter())
async def receive_feedback(message: types.Message):
    text = (message.text or message.caption or "").strip()
    attachment = feedback_attachment(message)
    if not text and not attachment:
        return await message.answer(
            "Этот тип сообщения пока не поддерживается. Отправьте текст, фото, видео, аудио или документ."
        )
    if len(text) > 3500:
        return await message.answer(
            "Сообщение слишком длинное. Сократите его до 3500 символов и отправьте ещё раз."
        )

    try:
        saved = add_user_feedback_message(
            message.from_user.id,
            message.from_user.username,
            text,
            telegram_message_id=message.message_id,
            media_group_id=message.media_group_id,
            **(attachment or {}),
        )
    except Exception as exc:
        print(f"Failed to save feedback: {type(exc).__name__}: {exc}")
        return await message.answer(
            "Не удалось сохранить обращение. Попробуйте отправить сообщение ещё раз."
        )
    if not saved:
        return await message.answer(
            "Не удалось сохранить обращение. Снова выберите «Обратная связь» и повторите отправку."
        )

    log_user_action(
        message.from_user.id,
        f"Feedback: created conversation {saved['conversation_id']}",
        message.from_user.username,
    )
    confirmation = (
        "✅ Сообщение и вложение переданы администратору."
        if attachment else
        "✅ Сообщение передано администратору."
    )
    await message.answer(f"{confirmation} Ответ придёт в этот чат от имени бота.")

    if BOT_OWNER_ID:
        username = f"@{message.from_user.username}" if message.from_user.username else "без username"
        try:
            header = (
                f"💬 Новое обращение #{saved['conversation_id']}\n"
                f"Пользователь: {username}\n"
                f"User ID: {message.from_user.id}\n\n"
                "Ответить можно в разделе «Обратная связь» административной панели."
            )
            if attachment:
                await message.bot.send_message(BOT_OWNER_ID, header)
                await message.bot.copy_message(
                    chat_id=BOT_OWNER_ID,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            else:
                await message.bot.send_message(BOT_OWNER_ID, f"{header}\n\n{text}")
        except Exception as exc:
            print(f"Failed to notify feedback owner: {type(exc).__name__}: {exc}")


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
