import asyncio
import time
import logging
from typing import Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import User
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.cache import valkey
from database.repository import UserRepository
from services.orchestrator import state

logger = logging.getLogger("DbMiddleware")


# ================= SAFE SESSION WRAPPER =================
class SafeSession:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, item):
        if self._session is None:
            raise RuntimeError("❌ Database hozir mavjud emas (session=None)")
        return getattr(self._session, item)


# ================= MIDDLEWARE =================
class DbSessionMiddleware(BaseMiddleware):

    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool
        super().__init__()

    async def __call__(self, handler, event, data):

        user_obj: User = data.get("event_from_user")
        if not user_obj:
            return await handler(event, data)

        user_id = user_obj.id

        # ================= L1 CACHE =================
        if user_id in state.l1_cache:
            cached = state.l1_cache[user_id]

            if cached.get("username") == user_obj.username:
                state.l1_cache.move_to_end(user_id)

                data["user"] = cached
                data["session"] = SafeSession(None)

                return await handler(event, data)

        # ================= L2 CACHE =================
        if valkey.is_alive:
            try:
                cached = await valkey.get("db_users", user_id)

                if cached:
                    # username change detect
                    if cached.get("username") != user_obj.username:
                        cached["username"] = user_obj.username
                        await self._enqueue_cache_update(cached)

                    data["user"] = cached
                    data["session"] = SafeSession(None)

                    # L1 update
                    state.l1_cache[user_id] = cached

                    return await handler(event, data)

            except Exception as e:
                logger.debug(f"L2 skip: {e}")

        # ================= CIRCUIT BREAKER =================
        async with state.db_lock:
            if not state.db_status:
                if time.time() - state.db_last_retry < state.cb_recovery_time:
                    data["user"] = self._emergency_user(user_obj)
                    data["session"] = SafeSession(None)
                    return await handler(event, data)

        # ================= DB =================
        try:
            async with self.session_pool() as session:

                try:
                    async with asyncio.timeout(2.5):
                        db_user = await UserRepository.get_or_create(session, user_obj)

                    user_data = self._model_to_dict(db_user)

                    # cache update
                    await self._enqueue_cache_update(user_data)

                    # L1 update
                    state.l1_cache[user_id] = user_data

                    data["user"] = user_data
                    data["session"] = SafeSession(session)

                    return await handler(event, data)

                except Exception as e:
                    await self._handle_db_failure(e)

                    data["user"] = self._emergency_user(user_obj)
                    data["session"] = SafeSession(None)

                    return await handler(event, data)

        except Exception as e:
            logger.error(f"POOL ERROR: {e}")

            data["user"] = self._emergency_user(user_obj)
            data["session"] = SafeSession(None)

            return await handler(event, data)

    # ================= CACHE QUEUE =================
    async def _enqueue_cache_update(self, user_data: Dict[str, Any]):
        try:
            state.cache_queue.put_nowait(user_data)
        except asyncio.QueueFull:
            try:
                state.cache_queue.get_nowait()
                state.cache_queue.put_nowait(user_data)
            except:
                pass

    # ================= MODEL → DICT =================
    def _model_to_dict(self, db_user) -> Dict[str, Any]:
        return {
            "user_id": db_user.user_id,
            "username": db_user.username,
            "status": db_user.status,
            "points": db_user.points,
            "referral_count": db_user.referral_count,
            "is_vip": db_user.is_vip,
            "vip_expire_date": (
                db_user.vip_expire_date.timestamp()
                if db_user.vip_expire_date else None
            )
        }

    # ================= EMERGENCY USER =================
    def _emergency_user(self, user_obj: User):
        return {
            "user_id": user_obj.id,
            "username": user_obj.username,
            "status": "user",
            "points": 0,
            "referral_count": 0,
            "is_vip": False,
            "vip_expire_date": None,
            "is_emergency": True
        }

    # ================= CIRCUIT BREAKER =================
    async def _handle_db_failure(self, e):
        async with state.db_lock:
            state.db_fail_count += 1

            if state.db_fail_count >= state.cb_threshold:
                state.db_status = False
                state.db_last_retry = time.time()

                logger.critical(f"🚨 DB DOWN: {e}")