# services/orchestrator.py
import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from database.cache import valkey
import orjson

logger = logging.getLogger("Orchestrator")

@dataclass
class AppState:
    l1_cache: OrderedDict = field(default_factory=OrderedDict)
    cache_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=10000))
    # DB Status
    db_status: bool = True
    db_fail_count: int = 0
    db_last_retry: float = 0
    db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Configs
    l1_max_size: int = 3000
    cb_threshold: int = 5
    cb_recovery_time: int = 30

state = AppState()

async def cache_orchestrator():
    """Background worker: Queue -> Batch -> Redis Pipeline -> L1."""
    logger.info("🚀 Cache Orchestrator: ACTIVE")
    
    while True:
        batch = []
        try:
            # 1. Navbatdan kamida bitta element kutish
            item = await state.cache_queue.get()
            batch.append(item)
            
            # 2. Mavjud bo'lgan boshqa elementlarni ham paketga yig'ish (max 100)
            while len(batch) < 100 and not state.cache_queue.empty():
                try:
                    batch.append(state.cache_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # 3. Redis Pipeline (Valkey ishlashini tekshirish)
            if valkey.is_alive and valkey.redis:
                try:
                    async with valkey.redis.pipeline(transaction=False) as pipe:
                        for entry in batch:
                            uid = entry['user_id']
                            # Kalit formatini Valkey manager orqali olish (Consistency!)
                            redis_key = f"app:db_users:{uid}:v1" # Yoki valkey._get_key
                            pipe.set(redis_key, orjson.dumps(entry), ex=3600)
                        await pipe.execute()
                except Exception as re:
                    logger.error(f"Valkey Pipeline Error: {re}")

            # 4. L1 Sync (Local Cache Update)
            for entry in batch:
                uid = entry['user_id']
                # L1 yangilashda OrderedDict LRU tartibini saqlash
                state.l1_cache[uid] = entry
                state.l1_cache.move_to_end(uid)
                
                if len(state.l1_cache) > state.l1_max_size:
                    state.l1_cache.popitem(last=False)

            # 5. Tasklarni yakunlash
            for _ in range(len(batch)): 
                state.cache_queue.task_done()
                
        except asyncio.CancelledError:
            logger.info("Stopping Orchestrator...")
            break
        except Exception as e:
            logger.error(f"Orchestrator Loop Error: {e}")
            await asyncio.sleep(1)