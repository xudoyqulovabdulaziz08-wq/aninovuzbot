import asyncio
import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Union

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import select

from database.models import DBUser
from database.cache import valkey

logger = logging.getLogger("DbMiddleware")

# ✅ 1. Kesh uchun global navbat (Limit bilan)
cache_queue = asyncio.Queue(maxsize=500)

async def cache_worker():
    """
    Ushbu worker fonda bitta-bitta keshni yangilaydi. 
    Bu asosiy Event Loop-ni tasklar bilan to'ldirib yubormaydi.
    """
    logger.info("👷 Cache Worker started.")
    while True:
        # Navbatdan foydalanuvchini olamiz
        user_data = await cache_queue.get()
        try:
            # ✅ 10/10 FIX: Keshga yozishda qat'iy timeout va shield
            await asyncio.wait_for(valkey.set_model(user_data), timeout=1.5)
        except Exception as e:
            logger.warning(f"🔴 Cache worker error: {e}")
        finally:
            cache_queue.task_done()

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool):
        self.session_pool = session_pool

    async def __call__(self, handler, event, data):
        async with self.session_pool() as session:
            user_obj: User = data.get("event_from_user")
            
            if user_obj:
                db_user = await self._resolve_user(session, user_obj)
                data["user"] = db_user or self._get_emergency_user(user_obj)
            
            data["db"] = session
            return await handler(event, data)

    def _get_emergency_user(self, user_obj: User) -> SimpleNamespace:
        return SimpleNamespace(user_id=user_obj.id, username=user_obj.username, status="user")

    async def _resolve_user(self, session, user_obj: User):
        # 1. Keshni tekshirish
        try:
            cached_data = await asyncio.wait_for(valkey.get("db_users", user_obj.id), timeout=0.8)
            if cached_data:
                # Username o'zgarmagan bo'lsa keshdan beramiz
                if cached_data.get("username") == user_obj.username:
                    return SimpleNamespace(**cached_data)
        except Exception:
            pass # Keshda yo'q yoki timeout bo'lsa DBga o'tamiz

        # 2. DB Fallback
        try:
            result = await session.execute(select(DBUser).where(DBUser.user_id == user_obj.id))
            db_user = result.scalar_one_or_none()

            if not db_user:
                db_user = DBUser(user_id=user_obj.id, username=user_obj.username, status="user")
                session.add(db_user)
                await session.commit()
                await session.refresh(db_user)
            elif db_user.username != user_obj.username:
                db_user.username = user_obj.username
                await session.commit()
                await session.refresh(db_user)

            # ✅ 2. create_task O'RNIGA navbatga qo'shamiz
            try:
                # Obyektni emas, dict ko'rinishini navbatga beramiz (DetachedInstanceError bo'lmasligi uchun)
                user_dict = {
                    "user_id": db_user.user_id,
                    "username": db_user.username,
                    "status": db_user.status
                }
                cache_queue.put_nowait(user_dict)
            except asyncio.QueueFull:
                logger.warning("⚠️ Cache queue full, skipping update.")

            return db_user
        except Exception as e:
            logger.error(f"❌ DB Failure: {e}")
            return None