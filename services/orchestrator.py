# services/orchestrator.py
import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from database.cache import valkey
import orjson

logger = logging.getLogger("Orchestrator")

@dataclass
class AppState:
    l1_cache: OrderedDict = field(default_factory=OrderedDict)
    cache_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=10000))
    db_status: bool = True
    db_fail_count: int = 0
    db_last_retry: float = 0
    db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    l1_max_size: int = 3000
    cb_threshold: int = 5
    cb_recovery_time: int = 30

state = AppState()

async def cache_orchestrator():
    """Background worker: Queue -> Redis -> L1 sync."""
    logger.info("🚀 Cache Orchestrator: ACTIVE")
    while True:
        batch = []
        try:
            item = await state.cache_queue.get()
            batch.append(item)
            while len(batch) < 100 and not state.cache_queue.empty():
                batch.append(state.cache_queue.get_nowait())

            # Redis Pipeline Sync
            if valkey.is_alive:
                async with valkey.redis.pipeline(transaction=False) as pipe:
                    for entry in batch:
                        pipe.set(f"db_users:{entry['user_id']}", orjson.dumps(entry), ex=3600)
                    await pipe.execute()

            # L1 Sync
            for entry in batch:
                uid = entry['user_id']
                state.l1_cache[uid] = entry
                state.l1_cache.move_to_end(uid)
                if len(state.l1_cache) > state.l1_max_size:
                    state.l1_cache.popitem(last=False)

            for _ in range(len(batch)): state.cache_queue.task_done()
        except Exception as e:
            logger.error(f"Orchestrator Error: {e}")
            await asyncio.sleep(1)