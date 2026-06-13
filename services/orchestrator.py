import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

import orjson
from database.cache import valkey

logger = logging.getLogger("AI-Orchestrator")


# ================= AI METRICS =================
@dataclass
class AIMetrics:
    total_requests: int = 0
    cache_writes_l1: int = 0
    cache_writes_l2: int = 0
    
    # ✅ FIX: defaultdict o'rniga oddiy dict ishlatildi (IndexError va ortiqcha xotira sarfini oldini oladi)
    hot_users: Dict[int, List[Any]] = field(default_factory=dict)

    avg_latency: float = 0.0
    last_batch_size: int = 0


metrics = AIMetrics()


# ================= STATE =================
@dataclass
class AppState:
    l1_cache: OrderedDict = field(default_factory=OrderedDict)

    # ✅ CRITICAL FIX: Queue global emas, asinxron funksiya ichida initsializatsiya qilinishi uchun Optional qilindi
    cache_queue: Optional[asyncio.Queue] = None

    l1_max_size: int = 8000
    is_running: bool = True
    dynamic_sleep: float = 0.01

    # dict ishlatish orqali keraksiz auto-vivification (bo'sh kalitlar ko'payishi) to'xtatildi
    user_score: Dict[int, float] = field(default_factory=dict)
    last_decay_time: float = field(default_factory=time.time)


state = AppState()


# ================= AI: HOT USER DETECTION =================
async def maybe_decay_heat_map():
    current_time = time.time()
    if current_time - state.last_decay_time < 600:
        return

    state.last_decay_time = current_time
    logger.info("🧹 Optimizing AI user heat map & scores asynchronously...")

    # Dictionary iteration paytida RuntimeError oldini olish uchun keys nusxalanadi
    user_keys = list(metrics.hot_users.keys())
    chunk_size = 500  
    
    for i, uid in enumerate(user_keys):
        user_data = metrics.hot_users.get(uid)
        if not user_data:
            continue
            
        score, last_active = user_data
        
        if current_time - last_active > 1200 or score <= 2:
            metrics.hot_users.pop(uid, None)
            state.user_score.pop(uid, None)
        else:
            if uid in metrics.hot_users:
                metrics.hot_users[uid][0] = score // 2

        if i % chunk_size == 0:
            await asyncio.sleep(0)


def update_user_heat(user_id: int):
    current_time = time.time()
    
    # Xavfsiz qiymat berish (IndexError yo'q)
    if user_id in metrics.hot_users:
        metrics.hot_users[user_id][0] += 1
        metrics.hot_users[user_id][1] = current_time
    else:
        metrics.hot_users[user_id] = [1, current_time]

    score = metrics.hot_users[user_id][0]

    if score > 50:
        state.user_score[user_id] = 0.2  
    elif score > 20:
        state.user_score[user_id] = 0.5  
    else:
        state.user_score[user_id] = 1.0  


def predict_ttl(user_id: int) -> int:
    score = state.user_score.get(user_id, 1.0)
    if score < 0.3:
        return 3600  
    elif score < 0.7:
        return 1800  
    else:
        return 600  


# ================= L1 CACHE MANAGEMENT =================
def l1_set(user_id: int, data: Dict[str, Any]):
    if user_id in state.l1_cache:
        state.l1_cache.move_to_end(user_id)
    state.l1_cache[user_id] = data

    if len(state.l1_cache) > state.l1_max_size:
        state.l1_cache.popitem(last=False)


# ================= MAIN ORCHESTRATOR =================
async def cache_orchestrator():
    logger.info("🧠 AI CACHE ORCHESTRATOR STARTED (PRO MODE)")

    # ✅ CRITICAL FIX: Queue ni aynan shu Event Loop ichida xavfsiz yaratish
    if state.cache_queue is None:
        state.cache_queue = asyncio.Queue(maxsize=30000)

    while state.is_running:
        raw_batch: List[Dict[str, Any]] = []
        start_time = time.time()

        try:
            await maybe_decay_heat_map()

            item = await state.cache_queue.get()
            raw_batch.append(item)

            for _ in range(300):
                try:
                    raw_batch.append(state.cache_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            for entry in raw_batch:
                u_id = entry.get("user_id")
                if u_id:
                    l1_set(u_id, entry)
                    update_user_heat(u_id)
                    metrics.cache_writes_l1 += 1
                    metrics.total_requests += 1

            deduplicated_batch = {}
            for entry in raw_batch:
                u_id = entry.get("user_id")
                if u_id:
                    deduplicated_batch[u_id] = entry

            # ✅ FIX: Pipeline uchun xavfsiz Asinxron Context Manager
            if valkey.is_alive and valkey.redis and deduplicated_batch:
                try:
                    async with valkey.redis.pipeline(transaction=False) as pipe:
                        for user_id, entry in deduplicated_batch.items():
                            ttl = predict_ttl(user_id)
                            key = f"{{ai:users}}:{user_id}:v1"
                            pipe.set(key, orjson.dumps(entry), ex=ttl)
                            metrics.cache_writes_l2 += 1
                        
                        await pipe.execute()
                except Exception as e:
                    logger.error(f"❌ Valkey Pipeline execution error: {e}")

            metrics.last_batch_size = len(raw_batch)
            latency = time.time() - start_time
            
            if metrics.avg_latency == 0.0:
                metrics.avg_latency = latency
            else:
                metrics.avg_latency = (metrics.avg_latency * 0.9) + (latency * 0.1)

            if len(raw_batch) > 200:
                state.dynamic_sleep = max(0.002, state.dynamic_sleep * 0.7)
            elif len(raw_batch) < 50:
                state.dynamic_sleep = min(0.05, state.dynamic_sleep * 1.1)

            await asyncio.sleep(state.dynamic_sleep)

        except asyncio.CancelledError:
            logger.warning("🛑 AI Orchestrator execution stopped via signal")
            break
        except Exception as e:
            logger.error(f"🔥 Orchestrator loop unexpected crash: {e}")
            await asyncio.sleep(1.0)
            
        finally:
            if raw_batch and state.cache_queue:
                for _ in range(len(raw_batch)):
                    state.cache_queue.task_done()


# ================= STATS API & STOP =================
def get_ai_stats() -> Dict[str, Any]:
    return {
        "total_processed_requests": metrics.total_requests,
        "l1_total_writes": metrics.cache_writes_l1,
        "l2_total_writes": metrics.cache_writes_l2,
        "avg_latency_ms": round(metrics.avg_latency * 1000, 2),
        "tracked_hot_users_count": len(metrics.hot_users),
        "last_batch_size": metrics.last_batch_size,
        "current_dynamic_sleep": round(state.dynamic_sleep, 4)
    }

async def stop_orchestrator():
    state.is_running = False
    logger.info("🛑 AI Cache Brain system stopping...")