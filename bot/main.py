### bot/main.py
import asyncio
from aiogram import Bot, Dispatcher
from handlers import register_handlers
from scheduler import start_scheduler
from dotenv import load_dotenv
import os

from db import migrate_add_notification_flags  # ⬅️ импорт функции миграции

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def main():
    migrate_add_notification_flags()  # ⬅️ вызов миграции

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    register_handlers(dp, bot)
    await start_scheduler(bot)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

