import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from aiogram import Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo

from bot.infra.db import migrate_add_notification_flags
from bot.agent_server.server import start_agent_ws_server
from bot.admin_console.server import start_admin_console
from bot.telegram.handlers import register_handlers
from bot.telegram.scheduler import start_scheduler
from bot.telegram.tracked_bot import TrackedBot

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()


async def configure_web_app_menu(bot):
    if not WEB_APP_URL:
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Webcheck",
                web_app=WebAppInfo(url=WEB_APP_URL),
            )
        )
    except Exception as exc:
        print(f"Failed to configure Telegram Mini App menu button: {type(exc).__name__}: {exc}")

async def main():
    migrate_add_notification_flags()

    bot = TrackedBot(token=BOT_TOKEN)
    await configure_web_app_menu(bot)
    dp = Dispatcher()
    register_handlers(dp, bot)
    await start_scheduler(bot)
    admin_runner = await start_admin_console(bot)
    agent_ws_runner = await start_agent_ws_server()
    try:
        await dp.start_polling(bot)
    finally:
        if agent_ws_runner:
            await agent_ws_runner.cleanup()
        if admin_runner:
            await admin_runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
