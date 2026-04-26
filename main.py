import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database.connection import AsyncSessionLocal, engine, check_db
from middlewares.db_middleware import DbSessionMiddleware, cache_worker 
from config import config
from database.cache import valkey
from handlers import start, admin, user, anime

# ✅ Global Task Tracker
background_tasks = set()
logger = logging.getLogger("Main")
base_url = config.WEBHOOK_URL.rstrip("/") # Webhook URL ni to'g'ri formatlash


async def health_check_handler(request):
    """Render va UptimeRobot uchun bot holatini tasdiqlovchi endpoint."""
    return web.Response(text="AniNowuz SaaS Engine is running! 🚀", status=200)

async def on_startup(bot: Bot):
    """Industrial Startup: Safety First."""
    
    # 1. Oldingi navbatdagi (spam) xabarlarni tozalash (MUHIM!)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🗑 Pending updates dropped.")

    if not config.WEBHOOK_URL:
        critical_error = "❌ WEBHOOK_URL is not set! Server cannot start."
        logger.critical(critical_error)
        raise ValueError(critical_error)

    # 2. Infra Check
    await check_db()
    try:
        await asyncio.wait_for(valkey.redis.ping(), timeout=2.0)
        logger.info("✅ Valkey (Redis) is online.")
    except Exception as e:
        logger.warning(f"⚠️ Redis unavailable: {e}. Bot running in DB-only mode.")

    # 3. Tables Sync
    async with engine.begin() as conn:
        from database.models import Base
        await conn.run_sync(Base.metadata.create_all)

    # 4. Webhook Setup
    
    await bot.set_webhook(
        url=f"{base_url}{config.WEBHOOK_PATH}", 
        allowed_updates=["message", "callback_query", "inline_query"],
        drop_pending_updates=True
    )

    # 5. Managed Worker Lifecycle
    for i in range(1, 4):
        task = asyncio.create_task(cache_worker(i), name=f"Worker-{i}")
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    logger.info(f"🔥 AniNowuz Engine Live | Workers: {len(background_tasks)}")

async def on_shutdown(bot: Bot):
    """Graceful Shutdown: No Ghost Tasks."""
    logger.info("🛑 Shutdown sequence initiated...")
    
    if background_tasks:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
    
    await bot.delete_webhook()
    await valkey.close()
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

    # --- 🛡 MIDDLEWARE REGISTRATION (Sizda shu yetishmayotgan edi) ---
    # Barcha update'lar uchun bazani tayyorlaydi
    dp.update.outer_middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))

    # --- 🔀 ROUTERS REGISTRATION ---
    dp.include_router(admin.router) # Admin birinchi
    dp.include_router(start.router)
    dp.include_router(anime.router)
    dp.include_router(user.router)

    # --- 🚀 LIFECYCLE ---
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", health_check_handler)
    
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=config.WEBHOOK_PATH)
    
    setup_application(app, dp, bot=bot)
    
    web.run_app(app, host="0.0.0.0", port=config.PORT)

if __name__ == "__main__":
    main()
    