import asyncio
import logging
import time
import orjson
from collections import deque
from types import SimpleNamespace
from typing import Any, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import DBUser
from database.cache import valkey

logger = logging.getLogger("DbMiddleware")

# --- GLOBAL STATE (Circuit Breaker & L1 Cache) ---
L1_CACHE: Dict[int, Dict[str, Any]] = {} # 🔥 L1: In-memory (Instant access)
L1_MAX_SIZE = 2000

DB_HEALTH = {"status": True, "fail_count": 0, "last_retry": 0} # 🛡 Circuit Breaker
CB_THRESHOLD = 5 # 5 marta xato bo'lsa zanjir uziladi
CB_RECOVERY_TIME = 15 # 15 sekundga DB dam oladi

# ✅ Industrial Batch Queue
cache_queue = asyncio.Queue(maxsize=5000)

async def cache_worker():
    """
    SaaS Overkill Worker: Redis Pipeline & Batch Processing.
    Har 50ms da yoki 50 ta item yig'ilganda Redis-ga paketlab yozadi.
    """
    logger.info("👷 Master Cache Worker: READY")
    batch = []
    
    while True:
        try:
            # Navbatdan itemni olish (50ms kutish bilan)
            try:
                item = await asyncio.wait_for(cache_queue.get(), timeout=0.05)
                batch.append(item)
            except asyncio.TimeoutError:
                pass # Batch'ni yozish vaqti keldi

            if batch and (len(batch) >= 50 or batch[-1] is None):
                # 🔥 FIX: Redis Pipeline (Batch Write)
                async with valkey.redis.pipeline(transaction=False) as pipe:
                    for entry in batch:
                        if entry:
                            pipe.set(f"db_users:{entry['user_id']}", orjson.dumps(entry), ex=3600)
                    await pipe.execute()
                
                # L1 Cache-ni ham yangilaymiz
                for entry in batch:
                    if entry:
                        L1_CACHE[entry['user_id']] = entry
                        if len(L1_CACHE) > L1_MAX_SIZE: # FIFO evict
                            L1_CACHE.pop(next(iter(L1_CACHE)))
                
                batch.clear()
                for _ in range(len(batch)): cache_queue.task_done()
                
        except Exception as e:
            logger.error(f"🔴 Pipeline Worker error: {e}")
            batch.clear()
            await asyncio.sleep(1)

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool

    async def __call__(self, handler, event, data):
        user_obj: User = data.get("event_from_user")
        if not user_obj: return await handler(event, data)

        # ✅ 1. L1 CACHE (In-Memory) - 0.001ms Latency
        l1_user = L1_CACHE.get(user_obj.id)
        if l1_user and l1_user['username'] == user_obj.username:
            data["user"] = SimpleNamespace(**l1_user)
            data["db"] = None
            return await handler(event, data)

        # ✅ 2. L2 CACHE (Redis) - Early Return
        try:
            async with asyncio.timeout(0.3):
                cached = await valkey.get("db_users", user_obj.id)
            if cached and cached.get("username") == user_obj.username:
                # L1-ga push qilamiz
                L1_CACHE[user_obj.id] = cached
                data["user"] = SimpleNamespace(**cached)
                data["db"] = None
                return await handler(event, data)
        except Exception: pass

        # ✅ 3. CIRCUIT BREAKER (DB Safety)
        if not DB_HEALTH["status"]:
            if time.time() - DB_HEALTH["last_retry"] > CB_RECOVERY_TIME:
                logger.info("🔧 Circuit Breaker: Attempting DB recovery...")
            else:
                data["user"] = self._get_emergency_user(user_obj)
                data["db"] = None
                return await handler(event, data)

        # ✅ 4. DB FALLBACK (L3)
        async with self.session_pool() as session:
            try:
                async with asyncio.timeout(1.5): # Hard DB Timeout
                    db_user = await self._resolve_db_user(session, user_obj)
                
                # Success: Reset Circuit Breaker
                DB_HEALTH["fail_count"] = 0
                DB_HEALTH["status"] = True
                
                data["user"] = db_user or self._get_emergency_user(user_obj)
                data["db"] = session
                return await handler(event, data)
            except Exception as e:
                # Failure: Update Circuit Breaker
                DB_HEALTH["fail_count"] += 1
                if DB_HEALTH["fail_count"] >= CB_THRESHOLD:
                    DB_HEALTH["status"] = False
                    DB_HEALTH["last_retry"] = time.time()
                    logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED! DB is offline: {e}")
                
                data["user"] = self._get_emergency_user(user_obj)
                data["db"] = session
                return await handler(event, data)

    async def _resolve_db_user(self, session, user_obj: User):
        result = await session.execute(select(DBUser).where(DBUser.user_id == user_obj.id))
        db_user = result.scalar_one_or_none()

        if not db_user:
            db_user = DBUser(user_id=user_obj.id, username=user_obj.username, status="user")
            session.add(db_user)
        elif db_user.username != user_obj.username:
            db_user.username = user_obj.username
        
        await session.commit()
        
        # Batch Worker uchun navbatga qo'shish
        user_data = {"user_id": db_user.user_id, "username": db_user.username, "status": db_user.status}
        if not cache_queue.full():
            cache_queue.put_nowait(user_data)
        
        return db_user

    def _get_emergency_user(self, user_obj: User):
        return SimpleNamespace(user_id=user_obj.id, username=user_obj.username, status="user", is_emergency=True)