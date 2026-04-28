import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database.connection import AsyncSessionLocal, engine, check_db
from database.events import attach_cache_listeners # ✅ Listenerlarni import qilish
from middlewares.db_middleware import DbSessionMiddleware
from services.cache_worker import CacheInvalidationWorker # ✅ Outbox worker klassi
from config import config
from database.cache import valkey
from handlers import start, admin, user, anime

# ✅ Global Task Tracker
background_tasks = set()
logger = logging.getLogger("Main")

async def health_check_handler(request):
    """Render va UptimeRobot uchun bot holatini tasdiqlovchi endpoint."""
    return web.Response(text="AniNowuz SaaS Engine is running! 🚀", status=200)



async def on_startup(bot: Bot):
    """Industrial Startup: Infra & Worker Sync."""
    
    # 1. Oldingi navbatdagi barcha xatoliklarni tozalash
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 2. Infra Check & Start
    await check_db()
    
    # ✅ Kesh menejerini (L1 + Stream Listener) start qilish
    await valkey.start()
    
    try:
        await asyncio.wait_for(valkey.redis.ping(), timeout=2.0)
        logger.info("✅ Valkey (Redis) is online.")
    except Exception as e:
        logger.warning(f"⚠️ Redis unavailable: {e}. Bot running in DB-only mode.")

    # 3. Tables Sync & Listeners
    async with engine.begin() as conn:
        from database.models import Base
        await conn.run_sync(Base.metadata.create_all)
    
    # ✅ SQLAlchemy Listenerlarni ulash
    attach_cache_listeners()

    # 4. Webhook Setup
    if not config.WEBHOOK_URL:
        raise ValueError("❌ WEBHOOK_URL is missing in environment variables!")

    await bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=["message", "callback_query", "inline_query"],
        drop_pending_updates=True
    )
    logger.info(f"🌐 Webhook Live: {config.WEBHOOK_URL}")

    # 5. Managed Outbox Workers
    # Biz yaratgan Outbox workerini asinxron ishga tushiramiz
    invalidation_worker = CacheInvalidationWorker(AsyncSessionLocal, valkey)
    
    worker_task = asyncio.create_task(invalidation_worker.run(), name="OutboxWorker")
    background_tasks.add(worker_task)
    worker_task.add_done_callback(background_tasks.discard)

    logger.info(f"🔥 AniNowuz Engine Live | Outbox Workers Active")

async def on_shutdown(bot: Bot):
    """Graceful Shutdown: Cleaning up everything."""
    logger.info("🛑 Shutdown sequence initiated...")
    
    # 1. Cancel background tasks
    if background_tasks:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
    
    # 2. Resurslarni tozalash
    await bot.delete_webhook()
    await valkey.stop() # ✅ Valkey stop (cleanup tasklarni o'chiradi)
    await engine.dispose()
    logger.info("✨ Clean shutdown complete.")

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # --- 🛡 MIDDLEWARE ---
    dp.update.outer_middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))
    
    
    # --- 🔀 ROUTERS ---
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(anime.router)
    dp.include_router(user.router)

    # --- 🚀 LIFECYCLE ---
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # --- 🌐 WEB APP ---
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    web.run_app(app, host="0.0.0.0", port=config.PORT)

if __name__ == "__main__":
    main()