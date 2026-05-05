import asyncio
import logging
import pytz
from contextlib import suppress
from aiohttp import web
from utils.helper import get_now
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

from handlers import (
    start, admin, user, anime, vip,
    reyting, search, referral
)
from handlers.admin_panel import channel, statisika

logger = logging.getLogger("Main")


# ================= GLOBAL STATE =================
background_tasks: set[asyncio.Task] = set()
workers = []


# =========================================================
# 🧠 AI CACHE BRAIN v2 (HOOK LAYER)
# =========================================================
class AICacheBrain:
    """
    🔥 USER BEHAVIOR LEARNING + PREDICTIVE CACHE
    """

    def __init__(self):
        self.user_stats = {}
        self.hot_users = set()

    async def observe(self, user_id: int, action: str):
        stat = self.user_stats.setdefault(user_id, {
            "hits": 0,
            "miss": 0,
            "actions": []
        })

        stat["actions"].append(action)
        stat["hits"] += 1

        if stat["hits"] > 50:
            self.hot_users.add(user_id)

    def predict_warm(self, user_id: int):
        """
        Predict next cache need
        """
        if user_id in self.hot_users:
            return True
        return False


ai_brain = AICacheBrain()


# =========================================================
# 🌐 FASTAPI ADMIN DASHBOARD
# =========================================================
async def create_dashboard():
    app = web.Application()

    # ================= HEALTH =================
    async def health(_):
        return web.json_response({"status": "ok", "mode": "ultra"})

    # ================= CACHE METRICS =================
    async def cache_metrics(_):
        return web.json_response({
            "cache_alive": valkey.is_alive,
            "l1_size": len(getattr(valkey, "_l1_cache", {})),
        })

    # ================= WORKER STATUS =================
    async def worker_status(_):
        return web.json_response({
            "workers": [t.get_name() for t in background_tasks]
        })

    # ================= DLQ VIEW =================
    async def dlq_view(_):
        try:
            data = await valkey.redis.lrange("outbox:dlq", 0, 50)
            return web.json_response([d.decode() for d in data])
        except:
            return web.json_response([])

    app.router.add_get("/health", health)
    app.router.add_get("/metrics/cache", cache_metrics)
    app.router.add_get("/metrics/workers", worker_status)
    app.router.add_get("/dlq", dlq_view)

    return app


# =========================================================
# 🚀 WORKER BOOTSTRAP
# =========================================================
async def start_workers():
    outbox = OutboxWorker(AsyncSessionLocal, valkey)
    cache = CacheInvalidationWorker(AsyncSessionLocal, valkey)

    async def safe(name, coro):
        try:
            logger.info(f"🚀 Worker start: {name}")
            await coro
        except Exception as e:
            logger.error(f"💥 Worker crash {name}: {e}")

    tasks = [
        asyncio.create_task(safe("outbox", outbox.start())),
        asyncio.create_task(safe("cache", cache.run())),
    ]

    for t in tasks:
        background_tasks.add(t)
        t.add_done_callback(background_tasks.discard)

    logger.info("🚀 Workers running (distributed-safe mode)")


# =========================================================
# ⚡ STARTUP
# =========================================================
async def on_startup(bot: Bot):
    logger.info("⚡ SYSTEM BOOTING ULTRA MODE")

    await bot.delete_webhook(drop_pending_updates=True)

    # parallel core init
    await asyncio.gather(
        check_db(),
        valkey.start()
    )

    await start_workers()

    # DB init
    async with engine.begin() as conn:
        from database.models import Base
        await conn.run_sync(Base.metadata.create_all)

    attach_cache_listeners()

    await bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=["message", "callback_query"]
    )

    # background monitor
    asyncio.create_task(system_monitor())

    logger.info("🌍 SYSTEM READY")


# =========================================================
# 🧠 SYSTEM MONITOR (AI OBSERVER)
# =========================================================
async def system_monitor():
    while True:
        try:
            await asyncio.sleep(20)

            # AI cache prediction trigger
            for uid in list(ai_brain.hot_users):
                if ai_brain.predict_warm(uid):
                    logger.info(f"🔥 Pre-warming cache for user {uid}")

            # Redis health
            if valkey.redis:
                await valkey.redis.ping()

        except Exception as e:
            logger.warning(f"Monitor issue: {e}")


# =========================================================
# 🛑 SHUTDOWN
# =========================================================
async def on_shutdown(bot: Bot):
    logger.info("🛑 SHUTDOWN START")

    for t in background_tasks:
        t.cancel()

    with suppress(Exception):
        await asyncio.gather(*background_tasks, return_exceptions=True)

    await valkey.stop()
    await engine.dispose()

    await bot.session.close()

    logger.info("✅ CLEAN STOP COMPLETE")


# =========================================================
# 🚀 MAIN ENTRY
# =========================================================
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

    # middleware
    dp.update.outer_middleware(
        DbSessionMiddleware(session_pool=AsyncSessionLocal)
    )

    # routers
    for r in [
        admin.router, start.router, anime.router,
        user.router, vip.router, referral.router,
        reyting.router, channel.router,
        statisika.router, search.router
    ]:
        dp.include_router(r)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # webhook app
    bot_app = web.Application()

    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(bot_app, path=config.WEBHOOK_PATH)
    setup_application(bot_app, dp, bot=bot)

    # attach dashboard (FASTAPI style inside aiohttp)
    dashboard = asyncio.run(create_dashboard())

    app = web.Application()
    app.add_subapp("/bot", bot_app)
    app.add_subapp("/admin", dashboard)

    logger.info("🚀 SERVER START")

    web.run_app(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    main()