import asyncio
import logging
import time
import orjson
from types import SimpleNamespace
from typing import Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import DBUser
from database.cache import valkey

logger = logging.getLogger("DbMiddleware")

# --- GLOBAL STATE ---
L1_CACHE: Dict[int, Dict[str, Any]] = {} 
L1_MAX_SIZE = 2000
DB_HEALTH = {"status": True, "fail_count": 0, "last_retry": 0}
CB_THRESHOLD = 5
CB_RECOVERY_TIME = 15

# ✅ Industrial Batch Queue
cache_queue = asyncio.Queue(maxsize=5000)

async def cache_worker(worker_id: int):
    """
    Redis Pipeline & Batch Processing Worker.
    """
    logger.info(f"👷 Worker-{worker_id}: DEPLOYED") 
    batch = []
    
    while True:
        try:
            # 1. Navbatdan itemlarni yig'ish (Batching)
            try:
                # 0.1 soniya kutamiz, agar xabar kelsa batchga qo'shamiz
                item = await asyncio.wait_for(cache_queue.get(), timeout=0.1)
                batch.append(item)
                
                # Agar navbatda yana xabarlar bo'lsa, ularni ham tezda yig'amiz (max 50 ta)
                while len(batch) < 50 and not cache_queue.empty():
                    item = cache_queue.get_nowait()
                    batch.append(item)
            except asyncio.TimeoutError:
                pass 

            # 2. Redis-ga paketlab yozish (Pipeline)
            if batch:
                async with valkey.redis.pipeline(transaction=False) as pipe:
                    for entry in batch:
                        # "db_users:ID" formatida orjson bilan yozish
                        pipe.set(f"db_users:{entry['user_id']}", orjson.dumps(entry), ex=3600)
                    await pipe.execute()
                
                # 3. L1 Cache yangilash va FIFO nazorati
                for entry in batch:
                    L1_CACHE[entry['user_id']] = entry
                    if len(L1_CACHE) > L1_MAX_SIZE:
                        # Eng eski elementni o'chirish (FIFO)
                        first_key = next(iter(L1_CACHE))
                        L1_CACHE.pop(first_key, None)
                    
                    cache_queue.task_done()
                
                batch.clear() 
                
        except Exception as e:
            logger.error(f"🔴 Pipeline Worker-{worker_id} error: {e}")
            batch.clear()
            await asyncio.sleep(2)

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool
        super().__init__()

    async def __call__(self, handler, event, data):
        user_obj: User = data.get("event_from_user")
        if not user_obj:
            return await handler(event, data)

        # 1. L1 CACHE (Instant)
        l1_user = L1_CACHE.get(user_obj.id)
        if l1_user and l1_user.get('username') == user_obj.username:
            async with self.session_pool() as session:
                data["user"] = SimpleNamespace(**l1_user)
                data["session"] = session
                return await handler(event, data)

        # 2. L2 CACHE (Redis)
        try:
            async with asyncio.timeout(0.3):
                # Valkey get() orjson.loads ishlatishini tekshiring
                cached = await valkey.get("db_users", user_obj.id)
            
            if cached and cached.get("username") == user_obj.username:
                L1_CACHE[user_obj.id] = cached
                async with self.session_pool() as session:
                    data["user"] = SimpleNamespace(**cached)
                    data["session"] = session
                    return await handler(event, data)
        except Exception:
            pass

        # 3. CIRCUIT BREAKER
        if not DB_HEALTH["status"]:
            if time.time() - DB_HEALTH["last_retry"] < CB_RECOVERY_TIME:
                data["user"] = self._get_emergency_user(user_obj)
                data["session"] = None 
                return await handler(event, data)
            logger.info("🔧 Circuit Breaker: Attempting DB recovery...")

        # 4. DB FALLBACK (L3)
        async with self.session_pool() as session:
            try:
                async with asyncio.timeout(2.0):
                    db_user = await self._resolve_db_user(session, user_obj)
                
                DB_HEALTH["fail_count"] = 0
                DB_HEALTH["status"] = True
                
                # Model ob'ektini handlerga uzatish
                data["user"] = db_user
                data["session"] = session
                return await handler(event, data)

            except Exception as e:
                DB_HEALTH["fail_count"] += 1
                if DB_HEALTH["fail_count"] >= CB_THRESHOLD:
                    DB_HEALTH["status"] = False
                    DB_HEALTH["last_retry"] = time.time()
                    logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {e}")
                
                data["user"] = self._get_emergency_user(user_obj)
                data["session"] = session
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
        await session.refresh(db_user) # ID va boshqa fieldlar yangilanishi uchun
        
        # Worker uchun dict tayyorlash
        user_data = {
            "user_id": db_user.user_id, 
            "username": db_user.username, 
            "status": db_user.status,
            "points": getattr(db_user, 'points', 0)
        }
        
        # Navbatga qo'shish
        if not cache_queue.full():
            cache_queue.put_nowait(user_data)
        
        return db_user

    def _get_emergency_user(self, user_obj: User):
        return SimpleNamespace(
            user_id=user_obj.id, 
            username=user_obj.username, 
            status="user", 
            is_emergency=True,
            points=0
        )