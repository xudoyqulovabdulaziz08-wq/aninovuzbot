import asyncio
import logging
import pytz
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database.connection import AsyncSessionLocal, engine, check_db
from database.events import attach_cache_listeners
from middlewares.db_middleware import DbSessionMiddleware
from services.cache_worker import CacheInvalidationWorker
from services.outbox.worker import OutboxWorker
from database.cache import valkey
from config import config
from handlers import start, admin, user, anime, vip, reyting, search, referral
from handlers.admin_panel import channel, statisika

logger = logging.getLogger("Main")

background_tasks = set()

# ================= HEALTH =================
async def health_check_handler(request):
    return web.Response(text="AniNowuz SaaS Engine is running! 🚀", status=200)


# ================= TIME =================
def get_now():
    return pytz.timezone("Asia/Tashkent").localize(
        __import__("datetime").datetime.now()
    )


# ================= WORKERS START =================
async def start_workers():
    tasks = []

    outbox_worker = OutboxWorker(AsyncSessionLocal)
    cache_worker = CacheInvalidationWorker(AsyncSessionLocal, valkey)

    # parallel start (MUHIM FIX ⚡)
    tasks.append(asyncio.create_task(outbox_worker.start(), name="OutboxWorker"))
    tasks.append(asyncio.create_task(cache_worker.run(), name="CacheWorker"))

    for t in tasks:
        background_tasks.add(t)
        t.add_done_callback(background_tasks.discard)

    logger.info("🚀 Workers started in PARALLEL mode")


# ================= STARTUP =================
async def on_startup(bot: Bot):
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🧹 Pending updates cleared")

    # ⚡ PARALLEL INIT (ENG MUHIM OPTIMIZATION)
    db_task = asyncio.create_task(check_db())
    redis_task = asyncio.create_task(valkey.start())

    await asyncio.gather(db_task, redis_task)

    # workers parallel start
    await start_workers()

    # DB schema (blocking faqat 1 marta)
    async with engine.begin() as conn:
        from database.models import Base
        await conn.run_sync(Base.metadata.create_all)

    attach_cache_listeners()

    # webhook setup
    await bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=["message", "callback_query", "inline_query"],
    )

    logger.info("🌐 Webhook active")

    # redis health check async (non-blocking)
    asyncio.create_task(_redis_ping())

    # middleware already optimal


async def _redis_ping():
    try:
        await asyncio.wait_for(valkey.redis.ping(), timeout=2)
        logger.info("✅ Redis OK")
    except Exception as e:
        logger.warning(f"Redis slow/unavailable: {e}")


# ================= SHUTDOWN =================
async def on_shutdown(bot: Bot):
    logger.info("🛑 Shutting down...")

    for t in background_tasks:
        t.cancel()

    await asyncio.gather(*background_tasks, return_exceptions=True)

    await valkey.stop()
    await engine.dispose()

    logger.info("✅ Clean shutdown complete")


# ================= MAIN =================
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

    # middleware (unchanged)
    dp.update.outer_middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))

    # routers (UNCHANGED — MUHIM)
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(anime.router)
    dp.include_router(user.router)
    dp.include_router(vip.router)
    dp.include_router(referral.router)
    dp.include_router(reyting.router)
    dp.include_router(channel.router)
    dp.include_router(statisika.router)
    dp.include_router(search.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # web app
    app = web.Application()
    app.router.add_get("/", health_check_handler)

    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=config.WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    web.run_app(
        app,
        host="0.0.0.0",
        port=config.PORT,
        handle_signals=True
    )


if __name__ == "__main__":
    main()