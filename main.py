import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database.connection import AsyncSessionLocal, engine, check_db
from middlewares.db_middleware import DbSessionMiddleware
from handlers import start
from database.events import *
from database.models import Base
from config import config

# ================= SOZLAMALAR =================
# Render sizga bepul domain beradi: https://SIZNING_BOT_NOMI.onrender.com
WEBHOOK_HOST = config.WEBHOOK_HOST            # .env dan oladi
WEBHOOK_PATH = f"/webhook/{config.BOT_TOKEN}"
WEBHOOK_URL  = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = config.PORT                 # Render PORT env o'zgaruvchisini beradi


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Jadvallar tayyor!")


async def on_startup(bot: Bot):
    await check_db()
    await create_tables()
    await bot.set_webhook(WEBHOOK_URL)
    print(f"🚀 Webhook o'rnatildi: {WEBHOOK_URL}")


async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    print("🛑 Webhook o'chirildi.")


def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.update.middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))
    dp.include_router(start.router)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)


if __name__ == "__main__":
    main()