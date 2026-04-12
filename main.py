import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# O'zimizning modullar
from database.connection import AsyncSessionLocal
from middlewares.db_middleware import DbSessionMiddleware
from handlers import start  # va boshqa handlerlar
from database.events import *  # SQLAlchemy eventlarini ulash
from database.cache import valkey  # Kesh managerini olish
from database.models import *  # Modellarni olish (agar kerak bo'lsa)
from config import config  # Konfiguratsiya faylidan kerakli o'zgaruvchilarni olish (masalan, TOKEN)

async def main():
    # Xatolarni konsolda ko'rish uchun
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    # 1. Middleware-ni ro'yxatdan o'tkazish
    dp.update.middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))

    # 2. Handlerlarni (Routerlarni) ulash
    dp.include_router(start.router)

    print("🚀 Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
