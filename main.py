import logging
from aiogram.types import User
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from redis import asyncio

from database.connection import AsyncSessionLocal, engine, check_db
from middlewares.db_middleware import DbSessionMiddleware
from handlers import start, admin, user, anime
import database.events as events
from database.models import Base
from config import config
from database.cache import valkey

# ✅ Named Logger
logger = logging.getLogger("Main")

async def create_tables():
    """Baza jadvallarini sinxronizatsiya qilish."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables are synchronized.")

async def __call__(self, handler, event, data):
    async with self.session_pool() as session:
        # data["session"] emas, data["db"] deb bering (agar handlerda db: AsyncSession bo'lsa)
        data["db"] = session 
        
        user_obj: User = data.get("event_from_user")
        if user_obj:
            try:
                # 3 soniya ichida foydalanuvchini topolmasa, xato bermasligi uchun
                db_user = await asyncio.wait_for(self._resolve_user(session, user_obj), timeout=3.0)
                data["user"] = db_user or self._get_emergency_user(user_obj)
            except asyncio.TimeoutError:
                data["user"] = self._get_emergency_user(user_obj)
                logger.warning(f"⚠️ User resolve timeout for {user_obj.id}")
        
        return await handler(event, data)

async def on_shutdown(bot: Bot):
    """Bot to'xtatilgandagi cleanup."""
    logger.info("🛑 Starting shutdown sequence...")
    
    await bot.delete_webhook()
    
    if bot.session:
        await bot.session.close()
    
    await valkey.close()
    await engine.dispose()
    
    logger.info("✅ All connections closed safely. Goodbye!")

async def index_handler(request):
    return web.Response(text="Aninovuz Bot is Running! 🚀", content_type="text/plain")

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

    # Webhook Application setup
    app = web.Application()
    # ✅ Mana bu qator asosiy sahifadagi 404 ni yo'qotadi:
    app.router.add_get("/", index_handler)
    
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=config.WEBHOOK_PATH)
    
    # ✅ MUTLOQ FIX: setup_application ichiga bot=bot qaytarildi. 
    # Busiz on_startup(bot) ishlamaydi va TypeError beradi.
    setup_application(app, dp, bot=bot) 

    # Serverni ishga tushirish
    logger.info(f"📡 Starting web server on port {config.PORT}")
    web.run_app(app, host="0.0.0.0", port=config.PORT)

if __name__ == "__main__":
    main()
