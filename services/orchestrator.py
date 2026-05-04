# services/orchestrator.py

import asyncio
import logging
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Any, List

import orjson
from database.cache import valkey

logger = logging.getLogger("AI-Orchestrator")


# ================= AI METRICS =================
@dataclass
class AIMetrics:
    total_requests: int = 0
    cache_hits_l1: int = 0
    cache_hits_l2: int = 0
    cache_misses: int = 0

    hot_users: Dict[int, int] = field(default_factory=lambda: defaultdict(int))

    avg_latency: float = 0.0
    last_batch_size: int = 0


metrics = AIMetrics()


# ================= STATE =================
@dataclass
class AppState:
    l1_cache: OrderedDict = field(default_factory=OrderedDict)

    cache_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=30000)
    )

    l1_max_size: int = 8000

    is_running: bool = True

    # adaptive engine
    dynamic_sleep: float = 0.01

    # prediction cache (AI TTL simulation)
    user_score: Dict[int, float] = field(default_factory=lambda: defaultdict(float))


state = AppState()


# ================= AI: HOT USER DETECTION =================
def update_user_heat(user_id: int):
    """
    AI-style behavior tracking
    """
    metrics.hot_users[user_id] += 1

    # normalize score
    score = metrics.hot_users[user_id]

    if score > 50:
        state.user_score[user_id] = 0.2   # VERY HOT → long cache
    elif score > 20:
        state.user_score[user_id] = 0.5   # medium hot
    else:
        state.user_score[user_id] = 1.0   # normal


def predict_ttl(user_id: int) -> int:
    """
    AI TTL prediction engine
    """
    score = state.user_score.get(user_id, 1.0)

    # hot users → longer cache
    if score < 0.3:
        return 3600   # 1 hour
    elif score < 0.7:
        return 1800   # 30 min
    else:
        return 600    # 10 min


# ================= L1 CACHE =================
def l1_set(user_id: int, data: Dict[str, Any]):
    state.l1_cache[user_id] = data
    state.l1_cache.move_to_end(user_id)

    if len(state.l1_cache) > state.l1_max_size:
        state.l1_cache.popitem(last=False)


# ================= MAIN ORCHESTRATOR =================
async def cache_orchestrator():
    """
    🚀 AI CACHE BRAIN ENGINE
    """

    logger.info("🧠 AI CACHE ORCHESTRATOR STARTED")

    while state.is_running:
        batch: List[Dict[str, Any]] = []
        start_time = time.time()

        try:
            # ================= WAIT FIRST =================
            item = await state.cache_queue.get()
            batch.append(item)

            # ================= BATCH COLLECT =================
            for _ in range(300):  # HIGH THROUGHPUT MODE
                try:
                    batch.append(state.cache_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # ================= PROCESS =================
            redis_pipe = None

            if valkey.is_alive and valkey.redis:
                redis_pipe = valkey.redis.pipeline(transaction=False)

            for entry in batch:
                user_id = entry.get("user_id")

                if not user_id:
                    continue

                metrics.total_requests += 1
                update_user_heat(user_id)

                # TTL prediction
                ttl = predict_ttl(user_id)

                # ================= L1 CACHE =================
                l1_set(user_id, entry)
                metrics.cache_hits_l1 += 1

                # ================= L2 CACHE (REDIS) =================
                if redis_pipe:
                    key = f"ai:users:{user_id}:v1"

                    redis_pipe.set(
                        key,
                        orjson.dumps(entry),
                        ex=ttl
                    )

            # ================= EXECUTE REDIS =================
            if redis_pipe:
                try:
                    await redis_pipe.execute()
                except Exception as e:
                    logger.error(f"Redis pipeline error: {e}")

            # ================= METRICS =================
            metrics.last_batch_size = len(batch)

            latency = time.time() - start_time
            metrics.avg_latency = (metrics.avg_latency * 0.9) + (latency * 0.1)

            # ================= ADAPTIVE SPEED =================
            if len(batch) > 200:
                state.dynamic_sleep = max(0.001, state.dynamic_sleep * 0.7)
            elif len(batch) < 50:
                state.dynamic_sleep = min(0.05, state.dynamic_sleep * 1.1)

            await asyncio.sleep(state.dynamic_sleep)

        except asyncio.CancelledError:
            logger.warning("🛑 AI Orchestrator stopped")
            break

        except Exception as e:
            logger.error(f"🔥 Orchestrator crash: {e}")
            await asyncio.sleep(1)


# ================= STATS API =================
def get_ai_stats():
    total = metrics.total_requests

    hit_rate = (
        (metrics.cache_hits_l1 / total) * 100
        if total > 0 else 0
    )

    return {
        "total_requests": total,
        "l1_hit_rate": round(hit_rate, 2),
        "avg_latency": round(metrics.avg_latency * 1000, 2),
        "hot_users": len(metrics.hot_users),
        "batch_size": metrics.last_batch_size
    }


# ================= STOP =================
async def stop_orchestrator():
    state.is_running = False
    logger.info("🛑 AI Cache Brain stopping...")