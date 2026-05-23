import os
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
    start 
)
from handlers.menu import(
    qolnlanma
)

logger = logging.getLogger("Main")
dp = Dispatcher()

# ================= GLOBAL STATE =================
background_tasks: set[asyncio.Task] = set()
workers = []



@dp.message()
async def echo_handler(message: types.Message):
    print(f"Xabar keldi: {message.text}")
    await message.answer("Men ishlayapman!")

async def health_check(request):
    return web.Response(text="Bot is alive!", status=200)
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
    app = web.Application()
    app.router.add_get('/', health_check)
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
# Fondagi abadiy vazifalar o'chib ketmasligi uchun global to'plam (Set) ochamiz
background_tasks = set()

async def on_startup(bot: Bot):
    logger.info("⚡ SYSTEM BOOTING ULTRA MODE")

    # 1. Eski webhooklarni tozalash
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🧹 Pending updates cleared and old webhook deleted.")
    except Exception as e:
        logger.error(f"❌ Error deleting webhook: {e}")

    # 2. Parallel core xizmatlarni yoqish (DB va Valkey)
    try:
        await asyncio.gather(
            check_db(),
            valkey.start()
        )
        logger.info("🔋 Database and Valkey storage connected successfully.")
    except Exception as e:
        logger.critical(f"💥 Core Infrastructure Failure (DB/Valkey): {e}")
        raise e

    # 3. WORKER'LARNI ISHGA TUSHIRISH
    # Agar start_workers ichida 'while True' bo'lsa, u pastdagi kodni bloklamasligi kerak
    try:
        # Workerlarni fonda xavfsiz ishga tushirish varianti (agar ichida abadiy loop bo'lsa):
        # worker_task = asyncio.create_task(start_workers())
        # background_tasks.add(worker_task)
        # worker_task.add_done_callback(background_tasks.discard)
        
        # Agar start_workers shunchaki tasklarni yaratib beradigan tezkor funksiya bo'lsa:
        await start_workers()
        logger.info("🤖 Background Outbox and Cleanup Workers deployed.")
    except Exception as e:
        logger.error(f"⚠️ Workers initialization error: {e}")

    # 4. Ma'lumotlar ombori jadvallarini tekshirish/yaratish
    try:
        async with engine.begin() as conn:
            from database.models import Base
            await conn.run_sync(Base.metadata.create_all)
        logger.info("📚 Database schemas synchronized.")
    except Exception as e:
        logger.error(f"⚠️ Database sync warning (tables might already exist): {e}")

    # 5. Kesh tinglovchilarini ulash
    attach_cache_listeners()

    # 6. TELEGRAM WEBHOOK'NI O'RNATISH
    if not config.WEBHOOK_URL:
        logger.critical("❌ WEBHOOK_URL is empty! Check your WEBHOOK_HOST environment variable.")
        raise RuntimeError("WEBHOOK_HOST is missing in production config!")

    try:
        logger.info(f"📡 Registering webhook url: {config.WEBHOOK_URL}")
        await bot.set_webhook(
            url=config.WEBHOOK_URL,
            allowed_updates=["message", "callback_query"]
        )
        logger.info("✅ Webhook successfully bound to Telegram API.")
    except Exception as e:
        logger.critical(f"💥 Failed to set webhook: {e}")
        raise e

    # 7. TIZIM MONITORINGINI FONDA XAVFSIZ RUN QILISH
    # Garbage Collector urib yubormasligi uchun background_tasks'ga qo'shamiz
    monitor_task = asyncio.create_task(system_monitor())
    background_tasks.add(monitor_task)
    monitor_task.add_done_callback(background_tasks.discard) # Task tugasa to'plamdan o'chadi

    logger.info("🌍 SYSTEM READY | PLATFORM IS ONLINE")

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
# ... (avvalgi importlar va funksiyalar)

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Dispatcher va Middleware'larni sozlash
    dp = Dispatcher()
    # dp.update.outer_middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))

    # Routerlarni qo'shish
    # dp.include_routers(start.router)
    dp.include_router(start.router)
    dp.include_router(qolnlanma.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # 1. Bitta asosiy aiohttp ilovasi (Sub-app'larsiz)
    app = web.Application()

    # 2. Render Health Check (/) -> Render xizmati o'chib qolmasligi uchun shart!
    async def render_health_check(request):
        return web.Response(text="Bot is live and healthy!", status=200)
    app.router.add_get('/', render_health_check)

    # 3. Webhook Handler integratsiyasi
    # Sizning config.WEBHOOK_PATH qiymatingiz avtomatik ravishda "/webhook/{token}" ni qaytaradi
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=config.WEBHOOK_PATH) 
    
    # Aiogram dasturini asosiy ilovaga ulaymiz
    setup_application(app, dp, bot=bot)

    # 4. Admin Dashboard Routerlari (Agar kerak bo'lsa)
    async def health(_):
        return web.json_response({"status": "ok", "mode": "ultra"})
    app.router.add_get("/admin/health", health)

    # ================= PORT BINDING FIX =================
    # Render o'zi taqdim etadigan PORT o'zgaruvchisini birinchi navbatda tekshiramiz.
    # Agar u bo'lmasa, config.PORT (8000) ga qaytadi.
    server_port = int(os.getenv("PORT", config.PORT))

    logger.info(f"🚀 SERVER STARTING ON PORT {server_port}")
    logger.info(f"🔒 Webhook path registered at: {config.WEBHOOK_PATH}")
    
    # run_app aiohttp event loop'ni Render'da barqaror ushlab turadi
    web.run_app(app, host="0.0.0.0", port=server_port)

if __name__ == "__main__":
    main()