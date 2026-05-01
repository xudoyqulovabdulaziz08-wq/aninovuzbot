import asyncio
import time
import logging
from types import SimpleNamespace

from aiogram import BaseMiddleware
from aiogram.types import User
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.cache import valkey
from database.repository import UserRepository
from services.orchestrator import state

logger = logging.getLogger("DbMiddleware")

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool
        super().__init__()

    async def __call__(self, handler, event, data):
        user_obj: User = data.get("event_from_user")
        if not user_obj:
            return await handler(event, data)

        # --- 1. L1 READ (Instant Memory) ---
        # L1 keshdan LRU uslubida o'qiymiz
        if user_obj.id in state.l1_cache:
            cached = state.l1_cache[user_obj.id]
            if cached.get('username') == user_obj.username:
                state.l1_cache.move_to_end(user_obj.id) # Oxirgi ishlatilgan deb belgilash
                data["user"] = SimpleNamespace(**cached)
                async with self.session_pool() as session:
                    data["session"] = session
                    return await handler(event, data)

        # --- 2. L2 READ (Redis / Valkey) ---
        if valkey.is_alive:
            try:
                cached = await valkey.get("db_users", user_obj.id)
                if cached and cached.get("username") == user_obj.username:
                    # Redis'dan topildi -> L1 ni yangilash uchun navbatga qo'shish
                    await self._enqueue_cache_update(cached)
                    data["user"] = SimpleNamespace(**cached)
                    async with self.session_pool() as session:
                        data["session"] = session
                        return await handler(event, data)
            except Exception as e:
                logger.debug(f"L2 Bypass: {e}")

        # --- 3. CIRCUIT BREAKER CHECK ---
        async with state.db_lock:
            if not state.db_status:
                if time.time() - state.db_last_retry < state.cb_recovery_time:
                    data["user"] = self._get_emergency_user(user_obj)
                    data["session"] = None
                    return await handler(event, data)
                logger.info("🔧 Circuit Breaker: Recovery attempt...")

        # --- 4. DB READ (L3 Fallback) ---
        # Middleware ichida DB READ qismi:
        try:
            async with self.session_pool() as session: 
                try:
                    async with asyncio.timeout(2.5):
                        db_user = await UserRepository.get_or_create(session, user_obj)
                
                    user_data = self._model_to_dict(db_user)
                    await self._enqueue_cache_update(user_data)
                
                    data["user"] = db_user
                    data["session"] = session
                    
                    # Handler sessiya ochiqligida chaqiriladi
                    return await handler(event, data) 

                except Exception as e:
                    # DB xatosi bo'lsa, handle_db_failure chaqiriladi
                    await self._handle_db_failure(e)
                    data["user"] = self._get_emergency_user(user_obj)
                    data["session"] = None 
                    return await handler(event, data)
        except Exception as global_e:
            # session_pool() o'zi xato bersa (masalan, ulanishlar to'lib ketgan bo'lsa)
            logger.error(f"Global DB Pool Error: {global_e}")
            data["user"] = self._get_emergency_user(user_obj)
            data["session"] = None
            return await handler(event, data)

    async def _enqueue_cache_update(self, user_data: dict):
        """Backpressure & Drop Policy bilan navbatga qo'shish."""
        try:
            state.cache_queue.put_nowait(user_data)
        except asyncio.QueueFull:
            # Eng eski xabarni o'chirib, yangisini qo'shish (Backpressure logic)
            try:
                state.cache_queue.get_nowait()
                state.cache_queue.put_nowait(user_data)
                logger.warning("⚠️ Cache Queue full: Dropped oldest entry to prioritize new one.")
            except: pass

    async def _handle_db_failure(self, e):
        """Circuit Breaker holatini yangilash."""
        async with state.db_lock:
            state.db_fail_count += 1
            if state.db_fail_count >= state.cb_threshold:
                state.db_status = False
                state.db_last_retry = time.time()
                logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {e}")

    def _model_to_dict(self, db_user) -> dict:
        """Model ob'ektini JSON serializable dict'ga o'tkazish."""
        return {
            "user_id": db_user.user_id,
            "username": db_user.username,
            "status": db_user.status,
            "points": getattr(db_user, 'points', 0),
            "referral_count": getattr(db_user, 'referral_count', 0),
            "is_vip": getattr(db_user, 'is_vip', False),
            "vip_expire_date": str(db_user.vip_expire_date) if getattr(db_user, 'vip_expire_date', None) else None
        }

    def _get_emergency_user(self, user_obj: User):
        """DB o'chganda xizmatni to'xtatmaslik uchun mock obyekt."""
        return SimpleNamespace(
            user_id=user_obj.id,
            username=user_obj.username,
            status="user",
            points=0,
            referral_count=0,
            is_vip=False,
            vip_expire_date=None,
            is_emergency=True
        )