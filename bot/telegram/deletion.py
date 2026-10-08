"""Confirm manual deletions before invoking persistence functions."""

import asyncio
import html
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.core.confirmation import ConfirmationStore


_confirmations = ConfirmationStore()


def _actor(user_id, message):
    return f"{user_id}:{message.chat.id}"


def _is_owner(user_id):
    return user_id == int(os.getenv("BOT_OWNER_ID", "0"))


async def _prompt(message, user_id, action, target_id, text):
    token = _confirmations.issue(action, target_id, _actor(user_id, message))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Подтвердить удаление", callback_data=f"dconfirm:{token}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"dcancel:{token}"),
    ]])
    await message.answer(text + "\n\nЭто действие нельзя отменить. Подтверждение действует 5 минут.",
                         reply_markup=keyboard, parse_mode="HTML")


async def prompt_site_deletion(message, user_id, site_id, *, admin=False):
    from bot.infra import db

    if admin and not _is_owner(user_id):
        return await message.answer("Нет доступа")
    site = (await asyncio.to_thread(db.get_site_by_id, site_id) if admin
            else await asyncio.to_thread(db.get_site_for_user, site_id, user_id))
    if not site:
        return await message.answer("Сайт уже удалён или не найден.")
    if not admin and await asyncio.to_thread(db.get_site_role, site_id, user_id) not in ("owner", "manager"):
        return await message.answer("Нет права удалять этот сайт.")
    text = f"Удалить сайт <b>{html.escape(site[3] or 'Без адреса')}</b> (ID {site_id}) из мониторинга?"
    if admin:
        text += f"\nПользователь: <code>{site[1]}</code>."
    await _prompt(message, user_id, "admin_site" if admin else "site", site_id, text)


async def prompt_user_deletion(message, user_id, target_user_id):
    from bot.infra import db

    if not _is_owner(user_id):
        return await message.answer("Нет доступа")
    profile = await asyncio.to_thread(db.get_admin_user, target_user_id)
    await _prompt(
        message, user_id, "user", target_user_id,
        f"Удалить <b>все данные</b> пользователя <code>{target_user_id}</code>?\n"
        f"Сайтов: {profile.get('site_count', 0)}. Будут удалены все его сайты, "
        "логи, записи сообщений и переписка обратной связи.",
    )


async def handle_deletion_confirmation(query):
    from bot.infra import db

    prefix, token = query.data.split(":", 1)
    if query.message is None:
        return await query.answer("Подтверждение недоступно", show_alert=True)
    pending = _confirmations.take(token, _actor(query.from_user.id, query.message))
    if not pending:
        return await query.answer("Подтверждение истекло или недоступно. Повторите действие.", show_alert=True)
    if prefix == "dcancel":
        await query.message.edit_text("Удаление отменено.", reply_markup=None)
        return await query.answer("Отменено")
    user_id = query.from_user.id
    if pending.action in ("user", "admin_site") and not _is_owner(user_id):
        return await query.answer("Нет доступа", show_alert=True)
    try:
        if pending.action == "user":
            sites, logs, messages = await asyncio.to_thread(db.delete_user_data, pending.target_id)
            text = (f"Данные пользователя {pending.target_id} удалены.\n"
                    f"Сайтов: {sites}, записей логов: {logs}, записей сообщений: {messages}.")
        elif pending.action == "admin_site":
            deleted = await asyncio.to_thread(db.admin_delete_site_by_id, pending.target_id)
            text = "Сайт удалён." if deleted else "Сайт уже удалён или не найден."
        else:
            # Recheck access because membership may change after the prompt.
            if await asyncio.to_thread(db.get_site_role, pending.target_id, user_id) not in ("owner", "manager"):
                return await query.answer("Нет права удалять этот сайт", show_alert=True)
            deleted = await asyncio.to_thread(db.delete_site_by_id, pending.target_id, user_id)
            text = "Сайт удалён." if deleted else "Сайт уже удалён или не найден."
    except ValueError as exc:
        if str(exc) != "owned_projects_have_members":
            raise
        await query.message.edit_text(
            "У пользователя есть проекты с участниками. Сначала перенесите права или удалите участников.",
            reply_markup=None,
        )
        return await query.answer("Удаление не выполнено", show_alert=True)
    await asyncio.to_thread(db.log_user_action, user_id,
                            f"Confirmed deletion: {pending.action} {pending.target_id}",
                            query.from_user.username)
    await query.message.edit_text(text, reply_markup=None)
    await query.answer("Готово")
