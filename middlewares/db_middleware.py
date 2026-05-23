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
from services.orchestrator import state, metrics

logger = logging.getLogger("DbMiddleware")


# ======================================================
# 🔥 L1 CACHE (LRU SAFE IMPLEMENTATION WITH THREAD-SAFETY)
# ======================================================
class L1Cache:
    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()  # Konkurent so'rovlar uchun xavfsizlik balansi

    async def get(self, key) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            # Keshdan olingan ma'lumotni mutatsiyadan asrash uchun nusxasini qaytaramiz
            return copy.deepcopy(self._cache[key])

    async def set(self, key, value):
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            
            # Ichki xotiradagi ma'lumot faqat toza nusxa bo'lishi shart
            self._cache[key] = copy.deepcopy(value)

            if len(self._cache) > self.max_size:
                removed = self._cache.popitem(last=False)
                logger.debug(f"🧹 L1 cache evicted: user_id={removed[0]}")

    def size(self):
        return len(self._cache)


# Global L1 keshni xavfsiz ishga tushirish
state.l1_cache = L1Cache(max_size=5000)

# Circuit Breaker boshlang'ich holatlarini xavfsiz tekshirish/yuklash
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
    Kesh rejimida bazaga ulanish taqiqlanganini nazorat qiluvchi,
    baza rejimida esa barcha metodlarni (jumladan context managerlarni) transparent o'tkazuvchi proxy.
    """
    def __init__(self, session):
        self.__dict__["_session"] = session

    async def __aenter__(self):
        if self._session is None:
            raise RuntimeError("❌ DB session is None (cache-only mode). Can't use context manager!")
        return await self._session.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session is None:
            return
        return await self._session.__aexit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, item):
        if self._session is None:
            raise RuntimeError(f"❌ DB session is None (cache-only mode). Can't access .{item}")
        return getattr(self._session, item)


# ======================================================
# 🔥 MIDDLEWARE CORE
# ======================================================
class DbSessionMiddleware(BaseMiddleware):

    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool
        # GC urib yubormasligi uchun fondagi vazifalarni vaqtincha saqlash to'plami
        self._background_tasks = set()
        super().__init__()

    async def __call__(self, handler, event, data):
        data["session_pool"] = self.session_pool
        user_obj: Optional[User] = data.get("event_from_user")

        # System/Channel/Chat postlari uchun xavfsiz fallback layer
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
        # 🔥 LEVEL 1: IN-MEMORY LRU CACHE (FAST PATH)
        # ======================================================
        cached_l1 = await state.l1_cache.get(user_id)
        if cached_l1:
            if (cached_l1.get("username") or "") != (user_obj.username or ""):
                logger.info(f"🔄 Username updated (L1): {user_id}")
                cached_l1["username"] = user_obj.username
                self._fire_and_forget_cache_update(cached_l1)

            data["user"] = cached_l1
            data["session"] = SafeSession(None)  # Kesh ishladi -> sessiya ochilmaydi
            return await handler(event, data)

        # ======================================================
        # 🔥 LEVEL 2: VALKEY/REDIS DISTRIBUTED CACHE
        # ======================================================
        if valkey.is_alive:
            try:
                # Key pattern loyiha standartiga moslashtirildi `{db_users}`
                cached_l2 = await valkey.get("{db_users}", user_id)
                if cached_l2:
                    cached_l2 = dict(cached_l2)

                    if (cached_l2.get("username") or "") != (user_obj.username or ""):
                        logger.info(f"🔄 Username updated (L2): {user_id}")
                        cached_l2["username"] = user_obj.username
                        self._fire_and_forget_cache_update(cached_l2)

                    await state.l1_cache.set(user_id, cached_l2)
                    data["user"] = cached_l2
                    data["session"] = SafeSession(None)
                    return await handler(event, data)

            except Exception as e:
                logger.exception(f"❌ L2 CACHE FAILURE user_id={user_id}: {e}")

        # ======================================================
        # 🔥 CIRCUIT BREAKER CHECK (PROTECTION LAYER)
        # ======================================================
        async with state.db_lock:
            if not state.db_status:
                if time.time() - state.db_last_retry < state.cb_recovery_time:
                    logger.warning(f"🚫 DB blocked (circuit open). Emergency mode for user_id={user_id}")
                    data["user"] = self._emergency_user(user_obj)
                    data["session"] = SafeSession(None)
                    return await handler(event, data)

        # ======================================================
        # 🔥 LEVEL 3: DATABASE ACCESS (SLOW PATH)
        # ======================================================
        # Tranzaksiya hayotiy tsikli (Lifecycle) handler to'liq tugaguncha ochiq qolishi shart!
        session = self.session_pool()
        try:
            start_time = time.time()
            async with asyncio.timeout(3.0):  # Yuklama ostida timeout biroz oshirildi (3.0s)
                db_user = await UserRepository.get_or_create(session, user_obj)

            duration = round(time.time() - start_time, 4)
            user_data = self._model_to_dict(db_user)

            # L1 va L2 keshlarini yangilash buyrug'ini yuborish
            await state.l1_cache.set(user_id, user_data)
            self._fire_and_forget_cache_update(user_data)

            data["user"] = copy.deepcopy(user_data)
            data["session"] = SafeSession(session)  # Handler ichida tranzaksiya qilishga ruxsat
            
            logger.info(f"🟢 DB HIT user_id={user_id} duration={duration}s")
            
            # Handlerni sessiya ochiq holatda ishga tushiramiz
            return await handler(event, data)

        except Exception as e:
            await self._handle_db_failure(e)
            logger.exception(f"❌ DB CORE ERROR user_id={user_id}")
            data["user"] = self._emergency_user(user_obj)
            data["session"] = SafeSession(None)
            return await handler(event, data)
            
        finally:
            # Handler tugagandan so'ng (yoki xato bo'lganda) sessiyani toza yopish
            await session.close()

    # ======================================================
    # 🔥 SAFE FIRE-AND-FORGET GARBAGE COLLECTOR PROOF
    # ======================================================
    def _fire_and_forget_cache_update(self, user_data: Dict[str, Any]):
        """GC urib yubormasligi kafolatlangan fondagi kesh yangilash taski"""
        task = asyncio.create_task(self._enqueue_cache_update(copy.deepcopy(user_data)))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _enqueue_cache_update(self, user_data: Dict[str, Any]):
        try:
            state.cache_queue.put_nowait(user_data)
        except asyncio.QueueFull:
            try:
                dropped = state.cache_queue.get_nowait()
                logger.warning(f"⚠️ Cache queue overflow, dropped: {dropped.get('user_id')}")
                state.cache_queue.put_nowait(user_data)
            except Exception as e:
                logger.error(f"❌ Cache queue push exception: {e}")

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

    async def _handle_db_failure(self, e):
        async with state.db_lock:
            state.db_fail_count += 1
            logger.warning(f"⚠️ Circuit Breaker Fail Counter: {state.db_fail_count}")

            if state.db_fail_count >= state.cb_threshold:
                state.db_status = False
                state.db_last_retry = time.time()
                logger.critical(f"🚨 CIRCUIT BREAKER STEPPED IN (OPENED): {e}")