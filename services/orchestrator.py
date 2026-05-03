# services/orchestrator.py
import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import orjson
from database.cache import valkey

logger = logging.getLogger("Orchestrator")


# ================= STATE =================
@dataclass
class AppState:
    l1_cache: OrderedDict = field(default_factory=OrderedDict)

    cache_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=10000)
    )

    # DB health
    db_status: bool = True
    db_fail_count: int = 0
    db_last_retry: float = 0.0
    db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # config
    l1_max_size: int = 3000
    cb_threshold: int = 5
    cb_recovery_time: int = 30

    # runtime
    is_running: bool = True


state = AppState()


# ================= ORCHESTRATOR =================
async def cache_orchestrator():
    """
    PRO MAX:
    - batch write (Redis pipeline)
    - L1 sync (LRU safe)
    - backpressure safe queue
    - low CPU sleep tuning
    """

    logger.info("🚀 Cache Orchestrator STARTED (PRO MODE)")

    while state.is_running:
        batch = []

        try:
            # ================= 1. WAIT FIRST ITEM =================
            item = await state.cache_queue.get()
            batch.append(item)

            # ================= 2. BATCH COLLECT =================
            # Fast drain (non-blocking)
            for _ in range(99):
                try:
                    batch.append(state.cache_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # ================= 3. REDIS PIPELINE WRITE =================
            if valkey.is_alive and valkey.redis:
                try:
                    async with valkey.redis.pipeline(transaction=False) as pipe:
                        for entry in batch:
                            uid = entry["user_id"]

                            key = f"app:db_users:{uid}:v1"

                            pipe.set(
                                key,
                                orjson.dumps(entry),
                                ex=3600
                            )

                        await pipe.execute()

                except Exception as e:
                    logger.error(f"❌ Redis pipeline error: {e}")

            # ================= 4. L1 CACHE SYNC (LRU SAFE) =================
            for entry in batch:
                uid = entry["user_id"]

                state.l1_cache[uid] = entry
                state.l1_cache.move_to_end(uid)

                if len(state.l1_cache) > state.l1_max_size:
                    state.l1_cache.popitem(last=False)

            # ================= 5. MARK TASK DONE =================
            for _ in batch:
                try:
                    state.cache_queue.task_done()
                except Exception:
                    pass

            # ================= 6. CPU YIELD (IMPORTANT) =================
            # 0 CPU burn protection
            await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.warning("🛑 Orchestrator cancelled")
            break

        except Exception as e:
            logger.error(f"🔥 Orchestrator crash: {e}")
            await asyncio.sleep(1)


# ================= STOP =================
async def stop_orchestrator():
    state.is_running = False
    logger.info("🛑 Orchestrator stopping...")