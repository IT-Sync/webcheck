### bot/main.py
import asyncio
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
import os

from bot.infra.db import migrate_add_notification_flags
from bot.admin_console.server import start_admin_console
from bot.telegram.handlers import register_handlers
from bot.telegram.scheduler import start_scheduler

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def main():
    migrate_add_notification_flags()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    register_handlers(dp, bot)
    await start_scheduler(bot)
    admin_runner = await start_admin_console(bot)
    try:
        await dp.start_polling(bot)
    finally:
        if admin_runner:
            await admin_runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
