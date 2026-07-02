### bot/main.py
import asyncio
from aiogram import Dispatcher
from dotenv import load_dotenv
import os

from bot.infra.db import migrate_add_notification_flags
from bot.agent_server.server import start_agent_ws_server
from bot.admin_console.server import start_admin_console
from bot.telegram.handlers import register_handlers
from bot.telegram.scheduler import start_scheduler
from bot.telegram.tracked_bot import TrackedBot

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def main():
    migrate_add_notification_flags()

    bot = TrackedBot(token=BOT_TOKEN)
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
