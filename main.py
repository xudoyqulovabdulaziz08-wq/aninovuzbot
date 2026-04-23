import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database.connection import AsyncSessionLocal, engine, check_db
from middlewares.db_middleware import DbSessionMiddleware
from handlers import start, admin, user, anime
import database.events as events
from database.models import Base
from config import config
from database.cache import valkey

# ✅ Named Logger (Root logger o'rniga)
logger = logging.getLogger("Main")

async def create_tables():
    """Baza jadvallarini sinxronizatsiya qilish."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables are synchronized.")

async def on_startup(bot: Bot):
    """Bot ishga tushgandagi lifecycle."""
    await check_db()
    
    # ✅ Defensive Redis Ping
    if hasattr(valkey, "redis"):
        try:
            await valkey.redis.ping()
            logger.info("✅ Valkey (Redis) connection successful.")
        except Exception as e:
            logger.warning(f"⚠️ Redis ping failed: {e}. Running without cache.")

    # Webhook sozlash
    await bot.delete_webhook(drop_pending_updates=True)
    await create_tables()
    
    await bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=["message", "callback_query", "inline_query"]
    )
    logger.info(f"🚀 Webhook set: {config.WEBHOOK_URL}")

async def on_shutdown(bot: Bot):
    """Bot to'xtatilgandagi cleanup."""
    logger.info("🛑 Starting shutdown sequence...")
    
    await bot.delete_webhook()
    
    if bot.session:
        await bot.session.close()
    
    await valkey.close()
    await engine.dispose()
    
    logger.info("✅ All connections closed safely. Goodbye!")

def main():
    # Logging konfiguratsiyasi
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Lifecycle registration
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Middleware integration
    dp.update.middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))

    # Router registration
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(anime.router)

    # ✅ Webhook Application setup (Redundancy fix)
    app = web.Application()
    
    # SimpleRequestHandler orqali webhook yo'lini bog'laymiz
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=config.WEBHOOK_PATH)
    
    # setup_application faqat aiohttp bilan dp lifecycle'ni bog'lash uchun
    setup_application(app, dp) # Bot bu yerda shart emas, chunki handler ichida bor

    # Serverni ishga tushirish
    logger.info(f"📡 Starting web server on port {config.PORT}")
    web.run_app(app, host="0.0.0.0", port=config.PORT)

if __name__ == "__main__":
    main()