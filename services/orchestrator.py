import asyncio
import logging
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

import orjson
from database.cache import valkey

logger = logging.getLogger("AI-Orchestrator")


# ================= AI METRICS =================
@dataclass
class AIMetrics:
    total_requests: int = 0
    cache_writes_l1: int = 0  # Write hisoblagichi
    cache_writes_l2: int = 0
    
    # RAM to'lib ketmasligi uchun sekin-asta pasaytiriladigan issiqlik lug'ati
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

    # adaptive engine speed
    dynamic_sleep: float = 0.01

    # prediction cache (AI TTL simulation)
    user_score: Dict[int, float] = field(default_factory=lambda: defaultdict(float))
    
    # Issiqlik xaritasini pasaytirish intervali (Har 10 minutda)
    last_decay_time: float = field(default_factory=time.time)


state = AppState()


# ================= AI: HOT USER DETECTION (SMOOTH & DECAY) =================
def update_user_heat(user_id: int):
    """
    AI-style behavior tracking with smooth memory decay (No Race Conditions).
    """
    current_time = time.time()
    
    # 🔥 CRITICAL FIX: .clear() o'rniga yumshoq pasaytirish (Smooth Decay).
    # Bu orqali xotira tozalanadi va parallel oqimdagi ma'lumotlar uzilib qolmaydi.
    if current_time - state.last_decay_time > 600:  # Har 10 minutda
        logger.info("🧹 Optimizing AI user heat map & scores to prevent memory leaks...")
        
        # Aktiv bo'lmagan foydalanuvchilarni xotiradan butkul tozalaymiz, faollarini ballini kamaytiramiz
        for uid in list(metrics.hot_users.keys()):
            if metrics.hot_users[uid] <= 2:
                del metrics.hot_users[uid]
                if uid in state.user_score:
                    del state.user_score[uid]
            else:
                metrics.hot_users[uid] = metrics.hot_users[uid] // 2  # Ballni pasaytirish
                
        state.last_decay_time = current_time

    metrics.hot_users[user_id] += 1
    score = metrics.hot_users[user_id]

    if score > 50:
        state.user_score[user_id] = 0.2   # VERY HOT → Uzoq muddatli kesh (AniNowuz loyihasi uchun)
    elif score > 20:
        state.user_score[user_id] = 0.5   # Medium hot
    else:
        state.user_score[user_id] = 1.0   # Normal


def predict_ttl(user_id: int) -> int:
    """
    AI TTL prediction engine based on behavior scores
    """
    score = state.user_score.get(user_id, 1.0)

    if score < 0.3:
        return 3600   # 1 soat (Ko'p ko'rilayotgan va faol foydalanuvchilar ma'lumoti)
    elif score < 0.7:
        return 1800   # 30 minut
    else:
        return 600    # 10 minut


# ================= L1 CACHE MANAGEMENT =================
def l1_set(user_id: int, data: Dict[str, Any]):
    """ LRU (Least Recently Used) uslubida ishlaydigan xavfsiz L1 xotira keshi """
    if user_id in state.l1_cache:
        state.l1_cache.move_to_end(user_id)
    state.l1_cache[user_id] = data

    if len(state.l1_cache) > state.l1_max_size:
        state.l1_cache.popitem(last=False)  # Eng eski elementni o'chirish (RAM himoyasi)


# ================= MAIN ORCHESTRATOR =================
async def cache_orchestrator():
    """
    🚀 AI CACHE BRAIN ENGINE - High Throughput, Cluster-Safe & Ultra Fast
    """
    logger.info("🧠 AI CACHE ORCHESTRATOR STARTED (PRO MODE)")

    while state.is_running:
        raw_batch: List[Dict[str, Any]] = []
        start_time = time.time()

        try:
            # 1. Queue-dan birinchi xabarni bloklanib kutish
            item = await state.cache_queue.get()
            raw_batch.append(item)

            # 2. High-Throughput yuklama: Qolgan xabarlarni non-blocking usulda yig'ish
            for _ in range(300):
                try:
                    raw_batch.append(state.cache_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # 🔥 CRITICAL FIX: L1 Local Cache barcha xabarlarni to'liq ko'rishi shart!
            # Deduplikatsiyadan oldin barcha xabarlarni L1 keshga va issiqlik xaritasiga yozamiz
            for entry in raw_batch:
                u_id = entry.get("user_id")
                if u_id:
                    l1_set(u_id, entry)
                    update_user_heat(u_id)
                    metrics.cache_writes_l1 += 1
                    metrics.total_requests += 1

            # ================= DEDUPLICATION FOR L2 (VALKEY) =================
            # Valkey/Redis tarmog'iga tushadigan yuklamani kamaytirish uchun faqat oxirgi holatni qoldiramiz
            deduplicated_batch = {}
            for entry in raw_batch:
                u_id = entry.get("user_id")
                if u_id:
                    deduplicated_batch[u_id] = entry

            # ================= VALKEY PIPELINE PREPARATION =================
            redis_pipe = None
            if valkey.is_alive and valkey.redis:
                # Tranzaksiyasiz pipeline (High performance bulk write)
                redis_pipe = valkey.redis.pipeline(transaction=False)

            for user_id, entry in deduplicated_batch.items():
                # AI model orqali eng optimal TTL qiymatini bashorat qilamiz
                ttl = predict_ttl(user_id)

                # L2 Distributed Valkey/Redis Cache-ga pipeline orqali joylash
                if redis_pipe:
                    # Redis Cluster arxitekturasiga mos keluvchi Hash Tags {...} pattern
                    key = f"{{ai:users}}:{user_id}:v1"
                    redis_pipe.set(
                        key,
                        orjson.dumps(entry),
                        ex=ttl
                    )
                    metrics.cache_writes_l2 += 1

            # ================= EXECUTE PIPELINE ASYNC =================
            if redis_pipe and len(deduplicated_batch) > 0:
                try:
                    await redis_pipe.execute()
                except Exception as e:
                    logger.error(f"❌ Valkey Pipeline execution error: {e}")

            # Navbatga ishlangan barcha elementlar yakunlanganini bildirish
            for _ in range(len(raw_batch)):
                state.cache_queue.task_done()

            # ================= METRICS UPDATE =================
            metrics.last_batch_size = len(raw_batch)
            latency = time.time() - start_time
            metrics.avg_latency = (metrics.avg_latency * 0.9) + (latency * 0.1)

            # ================= ADAPTIVE SPEED ENGINE =================
            # Tizim yuklamasiga qarab uxlash vaqtini dinamik sozlash
            if len(raw_batch) > 200:
                state.dynamic_sleep = max(0.001, state.dynamic_sleep * 0.7)  # Yuklama ko'p → Tezlashtirish
            elif len(raw_batch) < 50:
                state.dynamic_sleep = min(0.05, state.dynamic_sleep * 1.1)   # Yuklama kam → Tinchlantirish

            await asyncio.sleep(state.dynamic_sleep)

        except asyncio.CancelledError:
            logger.warning("🛑 AI Orchestrator execution stopped via signal")
            break
        except Exception as e:
            logger.error(f"🔥 Orchestrator loop unexpected crash: {e}")
            await asyncio.sleep(1.0)


# ================= STATS API =================
def get_ai_stats() -> Dict[str, Any]:
    total = metrics.total_requests
    return {
        "total_processed_requests": total,
        "l1_total_writes": metrics.cache_writes_l1,
        "l2_total_writes": metrics.cache_writes_l2,
        "avg_latency_ms": round(metrics.avg_latency * 1000, 2),
        "tracked_hot_users_count": len(metrics.hot_users),
        "last_batch_size": metrics.last_batch_size,
        "current_dynamic_sleep": round(state.dynamic_sleep, 4)
    }


# ================= STOP =================
async def stop_orchestrator():
    state.is_running = False
    logger.info("🛑 AI Cache Brain system stopping...")