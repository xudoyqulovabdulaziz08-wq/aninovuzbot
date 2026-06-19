import asyncio
import time
import logging
import copy
import inspect
from collections import OrderedDict
from typing import Any, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import User
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.cache import valkey
from database.repository import UserRepository
from services.orchestrator import state, metrics

logger = logging.getLogger("DbMiddleware")


# ======================================================
# 🔥 L1 CACHE (LRU SAFE IMPLEMENTATION WITH THREAD-SAFETY)
# ======================================================
class L1Cache:
    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()  

    async def get(self, key) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return copy.deepcopy(self._cache[key])

    async def set(self, key, value):
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            
            self._cache[key] = copy.deepcopy(value)

            if len(self._cache) > self.max_size:
                removed = self._cache.popitem(last=False)
                logger.debug(f"🧹 L1 cache evicted: user_id={removed[0]}")

    def size(self):
        return len(self._cache)


# Global L1 keshni xavfsiz ishga tushirish
state.l1_cache = L1Cache(max_size=5000)

# Circuit Breaker boshlang'ich holatlarini tekshirish
if not hasattr(state, 'db_status'): state.db_status = True
if not hasattr(state, 'db_fail_count'): state.db_fail_count = 0
if not hasattr(state, 'db_last_retry'): state.db_last_retry = 0.0
if not hasattr(state, 'db_lock'): state.db_lock = asyncio.Lock()
if not hasattr(state, 'cb_threshold'): state.cb_threshold = 5
if not hasattr(state, 'cb_recovery_time'): state.cb_recovery_time = 30.0


# ======================================================
# 🔥 SAFE SESSION PROXY (CONTEXT-AWARE MULTI-MODE)
# ======================================================
class SafeSession:
    """
    🧠 Aqlli Lazy Proxy + Post-Commit Hooks
    """
    def __init__(self, session=None, session_pool=None):
        self.__dict__["_session"] = session
        self.__dict__["_session_pool"] = session_pool
        self.__dict__["_post_commit_hooks"] = []  

    def on_commit(self, func):
        self._post_commit_hooks.append(func)

    async def commit(self):
        """Baza tasdiqlanadi va kesh tozalanadi"""
        if self._session is not None:
            await self._session.commit()
            logger.debug("💾 [DB PROXY] Global commit muvaffaqiyatli bajarildi.")
            
            for hook in self._post_commit_hooks:
                try:
                    res = hook()
                    if inspect.isawaitable(res):
                        await res
                except Exception as e:
                    logger.error(f"Post-commit hook xatosi: {e}")
        self._post_commit_hooks.clear()

    async def rollback(self):
        if self._session is not None:
            await self._session.rollback()
            logger.warning("🔄 [DB PROXY] Rollback bajarildi.")
        self._post_commit_hooks.clear()

    async def _ensure_session(self):
        if self._session is None:
            if self._session_pool is None:
                raise RuntimeError("❌ DB session is None va session_pool berilmagan.")
            logger.info("⚡ Lazy Loading: Dinamik sessiya ochildi.")
            self.__dict__["_session"] = self._session_pool()
        return self._session

    async def __aenter__(self):
        session = await self._ensure_session()
        return await session.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session is not None:
            return await self._session.__aexit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, item):
        """ ✅ Xavfsiz atribut wrapper """
        if self._session is not None:
            return getattr(self._session, item)

        def lazy_wrapper(*args, **kwargs):
            async def async_executor():
                sess = await self._ensure_session()
                attr = getattr(sess, item)
                if inspect.iscoroutinefunction(attr):
                    return await attr(*args, **kwargs)
                return attr(*args, **kwargs) if callable(attr) else attr
            return async_executor()
        return lazy_wrapper

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self.__dict__["_session"] = None


# ======================================================
# 🔥 MIDDLEWARE CORE
# ======================================================
class DbSessionMiddleware(BaseMiddleware):

    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool
        self._background_tasks = set()
        super().__init__()

    async def __call__(self, handler, event, data):
        data["session_pool"] = self.session_pool
        user_obj: Optional[User] = data.get("event_from_user")
        
        # Butun oqim uchun yagona boshqaruvchi proxy obyekt yaratamiz
        session_obj = SafeSession(session=None, session_pool=self.session_pool)
        data["session"] = session_obj
        
        try:
            # 1. System/Channel/Chat uchun fallback
            if not user_obj:
                data["user"] = {
                    "user_id": 0, "username": "System", "status": "system",
                    "points": 0, "referral_count": 0, "is_vip": False,
                    "vip_expire_date": None, "is_system": True
                }
                return await handler(event, data)
            
            user_id = user_obj.id

            # ======================================================
            # 🔥 LEVEL 1: IN-MEMORY LRU CACHE (FAST PATH)
            # ======================================================
            cached_l1 = await state.l1_cache.get(user_id)
            if cached_l1:
                if (cached_l1.get("username") or "") != (user_obj.username or ""):
                    logger.info(f"🔄 Username updated (L1): {user_id}")
                    cached_l1["username"] = user_obj.username
                    self._fire_and_forget_cache_update(cached_l1)

                data["user"] = cached_l1
                return await handler(event, data)

            # ======================================================
            # 🔥 LEVEL 2: VALKEY/REDIS DISTRIBUTED CACHE
            # ======================================================
            if valkey.is_alive:
                try:
                    cached_l2 = await valkey.get("{db_users}", user_id)
                    if cached_l2:
                        cached_l2 = dict(cached_l2)

                        if (cached_l2.get("username") or "") != (user_obj.username or ""):
                            logger.info(f"🔄 Username updated (L2): {user_id}")
                            cached_l2["username"] = user_obj.username
                            self._fire_and_forget_cache_update(cached_l2)

                        await state.l1_cache.set(user_id, cached_l2)
                        data["user"] = cached_l2
                        return await handler(event, data)

                except Exception as e:
                    logger.exception(f"❌ L2 CACHE FAILURE user_id={user_id}: {e}")

            # ======================================================
            # 🔥 CIRCUIT BREAKER CHECK & HALF-OPEN STATE
            # ======================================================
            async with state.db_lock:
                if not state.db_status:
                    if time.time() - state.db_last_retry < state.cb_recovery_time:
                        logger.warning(f"🚫 DB blocked (circuit open). Emergency mode for user_id={user_id}")
                        data["user"] = self._emergency_user(user_obj)
                        return await handler(event, data)
                    else:
                        logger.info(f"🔄 Circuit Breaker: HALF-OPEN rejimiga o'tdi. Bazani sinab ko'ramiz...")
                        state.db_status = True
                        state.db_fail_count = 0

            # ======================================================
            # 🔥 LEVEL 3: DATABASE ACCESS (SLOW PATH)
            # ======================================================
            try:
                async with asyncio.timeout(10.0):
                    # 🔥 FIX: Sessiyani proxy orqali to'g'ri ochamiz va uning daxlsizligini saqlaymiz
                    real_session = await session_obj._ensure_session()
                    user_data = await UserRepository.get_or_create(real_session, user_obj)

                await self._reset_circuit_breaker()

                await state.l1_cache.set(user_id, user_data)
                self._fire_and_forget_cache_update(user_data)

                data["user"] = copy.deepcopy(user_data)
                
                # Handlerni ishga tushiramiz
                result = await handler(event, data)
                
                # 🔥 CRITICAL COMMIT: Handler muvaffaqiyatli tugasa, o'zgarishlarni bazaga yozamiz
                await session_obj.commit()
                return result

            except Exception as e:
                # Muammo bo'lsa darhol orqaga qaytaramiz (Rollback)
                await session_obj.rollback()
                await self._handle_db_failure(e)
                logger.exception(f"❌ DB CORE ERROR user_id={user_id}: {e}")
                
                data["user"] = self._emergency_user(user_obj)
                return await handler(event, data)

        finally:
            # ======================================================
            # 🛡️ GLOBAL CLEANUP LAYER (NO MEMORY LEAKS)
            # ======================================================
            # ✅ MUTLAQ FIX: Proxy ichidagi real sessiyani yopish va tozalash zanjiri
            try:
                await session_obj.close()
            except Exception as e:
                logger.debug(f"SafeSession proxy close error (ignored): {e}")
            
            # Request ma'lumotlarini tozalaymiz (Xotirani bo'shatish)
            data.pop("session", None)
            data.pop("session_pool", None)

    def _fire_and_forget_cache_update(self, user_data: Dict[str, Any]):
        task = asyncio.create_task(self._enqueue_cache_update(copy.deepcopy(user_data)))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _enqueue_cache_update(self, user_data: Dict[str, Any]):
        try:
            # 🌟 DYNAMIC LAZY INITIALIZATION (MUMKIN BO'LGAN NONE XATOSINI OLDINI OLISH):
            if not hasattr(state, "cache_queue") or state.cache_queue is None:
                # Agar queue hali yaratilmagan bo'lsa, joriy loop ichida yaratamiz
                state.cache_queue = asyncio.Queue(maxsize=1000)
                logger.info("⚙️ [Cache Queue] Asinxron navbat dinamik ravishda yaratildi.")

            state.cache_queue.put_nowait(user_data)
        except asyncio.QueueFull:
            try:
                # Navbat to'lib ketganda eng birinchi eski elementni o'chiramiz
                dropped = state.cache_queue.get_nowait()
                logger.warning(f"⚠️ Cache queue overflow, dropped oldest update for user_id={dropped.get('user_id', 'unknown')}")
                state.cache_queue.put_nowait(user_data)
            except Exception as e:
                logger.error(f"❌ Cache queue push exception: {e}")
        except AttributeError as e:
            # Har qanday kutilmagan NoneType xatolaridan to'liq himoya
            logger.error(f"❌ Cache queue initsializatsiya xatoligi chetlab o'tildi: {e}")

    def _emergency_user(self, user_obj: User) -> Dict[str, Any]:
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

    async def _reset_circuit_breaker(self):
        async with state.db_lock:
            if not state.db_status or state.db_fail_count > 0:
                logger.info("🎉 DB connection is healthy. Circuit Breaker reset to CLOSED state.")
                state.db_fail_count = 0
                state.db_status = True

    async def _handle_db_failure(self, e):
        async with state.db_lock:
            state.db_fail_count += 1
            logger.warning(f"⚠️ Circuit Breaker Fail Counter: {state.db_fail_count}")

            if state.db_fail_count >= state.cb_threshold:
                state.db_status = False
                state.db_last_retry = time.time()
                logger.critical(f"🚨 CIRCUIT BREAKER STEPPED IN (OPENED): Baza quladi. Favqulodda rejim yoqildi.")