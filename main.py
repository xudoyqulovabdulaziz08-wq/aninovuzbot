import os
import asyncio
import logging
import orjson
from contextlib import suppress
from aiohttp import web

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database.connection import AsyncSessionLocal, engine, check_db
from database.events import attach_cache_listeners

from services.cache_worker import CacheInvalidationWorker
from services.outbox.worker import OutboxWorker
from database.cache import valkey

from config import config

# Router importlari (Faqat bitta joyda tartibli ulanadi)
from handlers import start
from handlers.menu import (
    qolnlanma, 
    reklama,
    search
    
)

logger = logging.getLogger("Main")

# ================= GLOBAL STATE =================
background_tasks: set[asyncio.Task] = set()


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

    def predict_warm(self, user_id: int) -> bool:
        """Predict next cache need"""
        return user_id in self.hot_users


ai_brain = AICacheBrain()


# =========================================================
# 🚀 WORKER BOOTSTRAP
# =========================================================
async def start_workers():
    """Fonda ishlovchi distributed workerlarni xavfsiz ishga tushirish"""
    outbox = OutboxWorker(AsyncSessionLocal, valkey)
    cache = CacheInvalidationWorker(AsyncSessionLocal, valkey)

    async def safe(name, coro):
        try:
            logger.info(f"🚀 Worker starting: {name}")
            await coro
        except asyncio.CancelledError:
            logger.warning(f"🛑 Worker {name} received cancellation signal")
        except Exception as e:
            logger.error(f"💥 Worker crash {name}: {e}")

    # Workerlarni alohida asyncio task qilib fonda yuritish
    tasks = [
        asyncio.create_task(safe("outbox", outbox.start())),
        asyncio.create_task(safe("cache", cache.run())),
    ]

    for t in tasks:
        background_tasks.add(t)
        t.add_done_callback(background_tasks.discard)

    logger.info("🚀 All background workers deployed successfully.")


# =========================================================
# 🧠 SYSTEM MONITOR (AI OBSERVER)
# =========================================================
async def system_monitor():
    """Tizim barqarorligini va kesh holatini tekshiruvchi asinxron monitor"""
    while True:
        try:
            await asyncio.sleep(30)  # Render resurslarini tejash uchun 30 soniya qilindi

            # AI cache prediction trigger Logics
            hot_list = list(ai_brain.hot_users)
            if hot_list:
                logger.info(f"📊 AI Active Hot Users Count: {len(hot_list)}")
                for uid in hot_list[:10]:  # Faqat dastlabki 10 tasini tekshirish (Overhead oldini olish)
                    if ai_brain.predict_warm(uid):
                        logger.debug(f"🔥 Pre-warming cache logic triggered for user {uid}")

            # Valkey/Redis health check
            if valkey.redis and valkey.is_alive:
                await valkey.redis.ping()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"⚠️ System Monitor issue: {e}")


# =========================================================
# ⚡ STARTUP & SHUTDOWN HANDLERS
# =========================================================
async def on_startup(bot: Bot):
    logger.info("⚡ SYSTEM BOOTING ULTRA MODE")

    # 1. Eski webhooklarni tozalash
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🧹 Pending updates cleared from Telegram servers.")
    except Exception as e:
        logger.error(f"❌ Error deleting webhook: {e}")

    # 2. Core infratuzilmalarni parallel ulash
    try:
        await asyncio.gather(
            check_db(),
            valkey.start()
        )
        logger.info("🔋 Database and Valkey storage systems connected.")
    except Exception as e:
        logger.critical(f"💥 Core Infrastructure Failure: {e}")
        raise e

    # 3. Workerlarni ishga tushirish
    await start_workers()

    # 4. DB sxemalarni sinxronizatsiya qilish
    try:
        async with engine.begin() as conn:
            from database.models import Base
            await conn.run_sync(Base.metadata.create_all)
        logger.info("📚 Database schemas verified.")
    except Exception as e:
        logger.error(f"⚠️ Database sync warning: {e}")

    # 5. Kesh tinglovchilarini ulash
    attach_cache_listeners()

    # 6. Telegram Webhook o'rnatish
    if not config.WEBHOOK_URL:
        logger.critical("❌ WEBHOOK_URL is missing in configuration!")
        raise RuntimeError("WEBHOOK_URL environment variable is required!")

    try:
        await bot.set_webhook(
            url=config.WEBHOOK_URL,
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"📡 Webhook registered successfully at: {config.WEBHOOK_URL}")
    except Exception as e:
        logger.critical(f"💥 Failed to set webhook: {e}")
        raise e

    # 7. Monitoringni fonda yoqish
    monitor_task = asyncio.create_task(system_monitor())
    background_tasks.add(monitor_task)
    monitor_task.add_done_callback(background_tasks.discard)

    logger.info("🌍 ANIMNOWUZ PLATFORM IS ONLINE & FULLY OPERATIONAL")


async def on_shutdown(bot: Bot):
    logger.info("🛑 SHUTDOWN SEQUENCE INITIATED")

    # Barcha fondagi tasklarni bekor qilish
    for t in background_tasks:
        t.cancel()

    with suppress(Exception):
        await asyncio.gather(*background_tasks, return_exceptions=True)

    # Resurslarni xavfsiz yopish
    await valkey.stop()
    await engine.dispose()
    await bot.session.close()

    logger.info("✅ CLEAN SHUTDOWN COMPLETE. SYSTEM OFFLINE.")


# =========================================================
# 🚀 MAIN ENTRY (AIOHTTP ARCHITECTURE)
# =========================================================
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )

    # 1. Bot va bitta unifikatsiyalangan Dispatcher yaratish
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # 2. Routerlarni global dispatcherga ulash (Ketma-ketlik muhim!)
    dp.include_router(start.router)
    dp.include_router(qolnlanma.router)
    dp.include_router(reklama.router)
    dp.include_router(search.router)

   

    # Startup va Shutdown signallarini ro'yxatdan o'tkazish
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # 3. Asosiy Web Application yaratish
    app = web.Application()

    # Render uchun majburiy Health Check (Root path)
    async def render_health_check(request):
        return web.Response(text="AniNowuz Bot is live and healthy!", status=200)
    app.router.add_get('/', render_health_check)

    # 4. ADMIN DASHBOARD ENDPOINTLARI (FIXED)
    async def admin_health(_):
        return web.json_response({"status": "ok", "mode": "ultra", "engine": "Valkey-AI"})

    async def cache_metrics(_):
        return web.json_response({
            "cache_alive": valkey.is_alive,
            "l1_size": len(getattr(valkey, "_l1_cache", {})),
        })

    async def worker_status(_):
        return web.json_response({
            "active_tasks_count": len(background_tasks)
        })

    async def dlq_view(_):
        try:
            if valkey.redis:
                # 💡 FIX: Worker yozadigan real kalitlar tekshiriladi
                # Sharded bo'lgani uchun barcha shard kalitlaridan yoki asosiy outbox navbatidan o'qiladi
                # Quyida eng ko'p xato yig'iladigan 'dlq:outbox' va 'cache:dlq' nazarda tutilgan
                data = await valkey.redis.lrange("dlq:outbox", 0, 49)
                
                # Agar klasterli sharding ishlatayotgan bo'lsangiz va kalit topilmasa, muqobil kalit:
                if not data:
                    data = await valkey.redis.lrange("{shard:0}:dlq:outbox", 0, 49)

                # 💡 FIX: JSON stringni real obyektga o'girib, chiroyli JSON holatda qaytaramiz
                cleaned_data = []
                for d in data:
                    try:
                        cleaned_data.append(orjson.loads(d))
                    except Exception:
                        cleaned_data.append(d.decode("utf-8")) # Agar string bo'lsa fallback
                
                return web.json_response(cleaned_data)
                
            return web.json_response({"error": "Valkey disconnected"}, status=503)
        except Exception as e:
            logger.error(f"Error in admin dlq endpoint: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # Admin routerlarini asosiy ilovaga qo'shish
    app.router.add_get("/admin/health", admin_health)
    app.router.add_get("/admin/metrics/cache", cache_metrics)
    app.router.add_get("/admin/metrics/workers", worker_status)
    app.router.add_get("/admin/dlq", dlq_view)

    # 5. Webhook Handler integratsiyasi
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=config.WEBHOOK_PATH) 
    
    # Aiogram kontekstini aiohttp ilovasiga xavfsiz bog'lash
    setup_application(app, dp, bot=bot)

    # 6. Render PORT binding sozlamasi
    server_port = int(os.getenv("PORT", config.PORT))
    logger.info(f"🚀 SERVER STARTING ON PORT {server_port}")
    
    # Ilovani ishga tushirish
    web.run_app(app, host="0.0.0.0", port=server_port)


if __name__ == "__main__":
    main()