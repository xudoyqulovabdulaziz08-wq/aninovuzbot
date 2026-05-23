import asyncio
import time
import logging
import copy
from collections import OrderedDict
from typing import Any, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import User
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.cache import valkey
from database.repository import UserRepository
from services.orchestrator import state

logger = logging.getLogger("DbMiddleware")


# ======================================================
# 🔥 L1 CACHE (LRU SAFE IMPLEMENTATION)
# ======================================================
class L1Cache:
    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._cache = OrderedDict()

    def get(self, key):
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key, value):
        if key in self._cache:
            self._cache.move_to_end(key)

        self._cache[key] = value

        if len(self._cache) > self.max_size:
            removed = self._cache.popitem(last=False)
            logger.debug(f"🧹 L1 cache evicted: user_id={removed[0]}")

    def size(self):
        return len(self._cache)


# global L1 cache
state.l1_cache = L1Cache(max_size=5000)


# ======================================================
# 🔥 SAFE SESSION WRAPPER
# ======================================================
class SafeSession:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, item):
        if self._session is None:
            raise RuntimeError("❌ DB session is None (cache-only mode)")
        return getattr(self._session, item)


# ======================================================
# 🔥 MIDDLEWARE
# ======================================================
class DbSessionMiddleware(BaseMiddleware):

    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool
        super().__init__()

    async def __call__(self, handler, event, data):
        data["session_pool"] = self.session_pool
        user_obj: Optional[User] = data.get("event_from_user")

        # ======================================================
        # 🔥 CRITICAL FIX: Foydalanuvchi bo'lmasa xavfsiz fallback yaratish
        # ======================================================
        if not user_obj:
            data["user"] = {
                "user_id": 0,
                "username": "System",
                "status": "system",
                "points": 0,
                "referral_count": 0,
                "is_vip": False,
                "vip_expire_date": None,
                "is_system": True
            }
            data["session"] = SafeSession(None)
            return await handler(event, data)

        user_id = user_obj.id

        # ======================================================
        # 🔥 L1 CACHE (FASTEST)
        # ======================================================
        cached_l1 = state.l1_cache.get(user_id)
        if cached_l1:
            try:
                state.l1_cache.set(user_id, cached_l1)
                cached_copy = copy.deepcopy(cached_l1)

                if (cached_copy.get("username") or "") != (user_obj.username or ""):
                    logger.info(f"🔄 Username updated (L1): {user_id}")
                    cached_copy["username"] = user_obj.username
                    # Fonga berib yuboramiz, handler kutib qolmasligi uchun
                    asyncio.create_task(self._enqueue_cache_update(cached_copy))

                data["user"] = cached_copy
                data["session"] = SafeSession(None)
                logger.debug(f"⚡ L1 hit user_id={user_id}")
                return await handler(event, data)

            except Exception as e:
                logger.exception(f"❌ L1 CACHE ERROR user_id={user_id}: {e}")

        # ======================================================
        # 🔥 L2 CACHE (VALKEY/REDIS)
        # ======================================================
        if valkey.is_alive:
            try:
                cached_l2 = await valkey.get("db_users", user_id)
                if cached_l2:
                    cached_l2 = dict(cached_l2)

                    if (cached_l2.get("username") or "") != (user_obj.username or ""):
                        logger.info(f"🔄 Username updated (L2): {user_id}")
                        cached_l2["username"] = user_obj.username
                        # FIX: await emas, fonga task qilib beramiz UX tezligi uchun
                        asyncio.create_task(self._enqueue_cache_update(cached_l2))

                    state.l1_cache.set(user_id, copy.deepcopy(cached_l2))
                    data["user"] = cached_l2
                    data["session"] = SafeSession(None)
                    logger.debug(f"⚡ L2 hit user_id={user_id}")
                    return await handler(event, data)

            except Exception as e:
                logger.exception(f"❌ L2 CACHE ERROR user_id={user_id}: {e}")

        # ======================================================
        # 🔥 CIRCUIT BREAKER CHECK
        # ======================================================
        async with state.db_lock:
            if not state.db_status:
                if time.time() - state.db_last_retry < state.cb_recovery_time:
                    logger.warning(f"🚫 DB blocked (circuit open) user_id={user_id}")
                    data["user"] = self._emergency_user(user_obj)
                    data["session"] = SafeSession(None)
                    return await handler(event, data)

        # ======================================================
        # 🔥 DATABASE ACCESS (SLOW PATH)
        # ======================================================
        try:
            async with self.session_pool() as session:
                try:
                    start = time.time()
                    async with asyncio.timeout(2.5):
                        db_user = await UserRepository.get_or_create(session, user_obj)

                    duration = round(time.time() - start, 4)
                    user_data = self._model_to_dict(db_user)
                    safe_data = copy.deepcopy(user_data)

                    # Fon rejimidagi kesh yangilanishi
                    asyncio.create_task(self._enqueue_cache_update(safe_data))
                    state.l1_cache.set(user_id, safe_data)

                    data["user"] = user_data
                    data["session"] = SafeSession(session)
                    logger.info(f"🟢 DB HIT user_id={user_id} time={duration}s")
                    return await handler(event, data)

                except Exception as e:
                    await self._handle_db_failure(e)
                    logger.exception(f"❌ DB ERROR user_id={user_id}")
                    data["user"] = self._emergency_user(user_obj)
                    data["session"] = SafeSession(None)
                    return await handler(event, data)

        except Exception as e:
            logger.critical(f"💥 DB POOL ERROR user_id={user_id}: {e}")
            data["user"] = self._emergency_user(user_obj)
            data["session"] = SafeSession(None)
            return await handler(event, data)

    # ======================================================
    # 🔥 CACHE QUEUE
    # ======================================================
    async def _enqueue_cache_update(self, user_data: Dict[str, Any]):
        try:
            state.cache_queue.put_nowait(user_data)
        except asyncio.QueueFull:
            try:
                dropped = state.cache_queue.get_nowait()
                logger.warning(f"⚠️ Cache queue overflow, dropped: {dropped.get('user_id')}")
                state.cache_queue.put_nowait(user_data)
            except Exception as e:
                logger.error(f"❌ Cache queue fatal error: {e}")

    # ======================================================
    # 🔥 MODEL SERIALIZER
    # ======================================================
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

    # ======================================================
    # 🔥 EMERGENCY MODE
    # ======================================================
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

    # ======================================================
    # 🔥 CIRCUIT BREAKER
    # ======================================================
    async def _handle_db_failure(self, e):
        async with state.db_lock:
            state.db_fail_count += 1

            logger.warning(f"⚠️ DB fail count: {state.db_fail_count}")

            if state.db_fail_count >= state.cb_threshold:
                state.db_status = False
                state.db_last_retry = time.time()

                logger.critical(f"🚨 CIRCUIT BREAKER OPEN: {e}")