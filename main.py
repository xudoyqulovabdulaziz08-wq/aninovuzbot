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
async def health_check_handler(request):
    """Render va UptimeRobot uchun bot holatini tasdiqlovchi endpoint."""
    return web.Response(text="AniNowuz SaaS Engine is running! 🚀", status=200)
async def on_startup(bot: Bot):
    """Industrial Startup: Safety First."""
    # 1. Webhook URL Validatsiyasi (Silent Failure protection)
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
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=["message", "callback_query", "inline_query"]
    )

    # 5. Managed Worker Lifecycle
    for i in range(1, 4):
        task = asyncio.create_task(cache_worker(i), name=f"Worker-{i}")
        background_tasks.add(task)
        # Task o'z-o'zidan tugasa, set'dan o'chirish (Memory safety)
        task.add_done_callback(background_tasks.discard)

    logger.info(f"🔥 AniNowuz Engine Live | Workers: {len(background_tasks)}")

async def on_shutdown(bot: Bot):
    """Graceful Shutdown: No Ghost Tasks."""
    logger.info("🛑 Shutdown sequence initiated...")
    
    # 1. Cancel Background Workers
    if background_tasks:
        logger.info(f"Closing {len(background_tasks)} background workers...")
        for task in background_tasks:
            task.cancel()
        # Workerlar yopilishini kutish
        await asyncio.gather(*background_tasks, return_exceptions=True)
    
    # 2. Webhook Cleanup
    await bot.delete_webhook()
    
    # 3. Connections Cleanup
    await valkey.close()
    await engine.dispose()
    
    logger.info("✨ Clean shutdown complete. System offline.")

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

    # Registration
    # Routers Registration
    dp.include_router(admin.router) # Admin har doim birinchi
    dp.include_router(start.router)
    dp.include_router(anime.router) # Anime qidiruv va ro'yxat
    dp.include_router(user.router)  # Profil va sozlamalar
    # ... qolgan routerlar

    app = web.Application()
    app.router.add_get("/", health_check_handler) # Health Check Endpoint
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=config.WEBHOOK_PATH)
    
    setup_application(app, dp, bot=bot)
    
    web.run_app(app, host="0.0.0.0", port=config.PORT)

if __name__ == "__main__":
    main()