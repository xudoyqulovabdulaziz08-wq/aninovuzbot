import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from database.connection import AsyncSessionLocal, engine, check_db
from middlewares.db_middleware import DbSessionMiddleware
from handlers import start
from database.events import *
from database.cache import valkey
from database.models import Base
from config import config


async def create_tables():
    """Jadvallarni avtomatik yaratish (agar mavjud bo'lmasa)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Jadvallar tayyor!")


async def main():
    logging.basicConfig(level=logging.INFO)

    # 1. DB ulanishni tekshirish
    await check_db()

    # 2. Jadvallarni yaratish
    await create_tables()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)

    # 3. Middleware ulash
    dp.update.middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))

    # 4. Handlerlarni ulash
    dp.include_router(start.router)

    print("🚀 Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())