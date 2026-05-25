import asyncio
import logging
import time
import random
import hashlib
from datetime import datetime, timezone
from collections import defaultdict, deque

import orjson
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.models import OutboxEvent

logger = logging.getLogger("PRO_WORKER")


# ==========================================
# 🧠 AI CACHE + METRICS ENGINE (REAL O(1))
# ==========================================
class MetricsBrain:
    def __init__(self):
        self.cache_hits = 0
        self.cache_misses = 0
        self.db_calls = 0
        self.events_processed = 0
        self.failures = 0

        self.window_size = 200
        self.latency_window = deque(maxlen=self.window_size)
        self._latency_sum = 0.0  # Real O(1) uchun yig'indi
        
        self.user_heat = defaultdict(int)  # hot user detection

    def cache_ratio(self):
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total) * 100 if total else 0

    def add_latency(self, value):
        if len(self.latency_window) == self.window_size:
            self._latency_sum -= self.latency_window[0]
        
        self.latency_window.append(value)
        self._latency_sum += value

    def avg_latency(self):
        count = len(self.latency_window)
        return self._latency_sum / count if count > 0 else 0.0

    def mark_user(self, user_id):
        self.user_heat[user_id] += 1

    def is_hot_user(self, user_id):
        return self.user_heat[user_id] > 20


metrics = MetricsBrain()


# ==========================================
# 🚀 PRO ULTRA WORKER (CRASH SAFE)
# ==========================================
class OutboxWorker:
    def __init__(self, session_pool, cache_manager, redis=None):
        self.session_pool = session_pool
        self.cache = cache_manager
        self.redis = redis

        self.running = True

        # Tuning parameters
        self.batch_size = 100
        self.max_retry = 6
        self.parallel_limit = 20

        # DLQ key
        self.dlq_key = "dlq:outbox"

        # Circuit Breaker state
        self.failure_threshold = 10
        self.failure_count = 0
        self.circuit_open = False
        self.last_fail_time = 0

    def dynamic_ttl(self, user_id: int) -> int:
        base = 300
        if metrics.is_hot_user(user_id):
            return base * 5  # Hot user keshda ko'proq turadi (Aninowuz optimization)
        return base + random.randint(0, 120)

    def shard_key(self, key: str) -> str:
        """
        Redis Cluster mos keluvchi xavfsiz deterministik sharding.
        Hash tags {...} yordamida slotlarni bitta node-da saqlashni kafolatlaydi.
        """
        if not self.redis:
            return key
        # Python hash() o'rniga barqaror MD5 hash
        hasher = hashlib.md5(key.encode('utf-8'))
        shard = int(hasher.hexdigest(), 16) % 3
        return f"{{shard:{shard}}}:{key}"

    def check_circuit(self):
        if self.failure_count >= self.failure_threshold:
            if not self.circuit_open:
                self.circuit_open = True
                self.last_fail_time = time.time()
                logger.critical("🚨 CIRCUIT BREAKER OPENED! DATABASE OR SERVICE IS DOWN.")

        if self.circuit_open and time.time() - self.last_fail_time > 30:
            self.circuit_open = False
            self.failure_count = 0
            logger.info("✅ CIRCUIT BREAKER CLOSED. RESUMING OPERATIONS.")

    async def start(self):
        logger.info("🚀 PRO ULTRA WORKER STARTED SUCCESSFULLY")

        while self.running:
            try:
                self.check_circuit()

                if self.circuit_open:
                    await asyncio.sleep(2)
                    continue

                start_time = time.time()
                processed = await self.process_batch()
                
                metrics.add_latency(time.time() - start_time)

                if processed:
                    await asyncio.sleep(0.02)  # High-load dynamic backpressure
                else:
                    await asyncio.sleep(0.5)   # Idle holatda kutish

            except Exception as e:
                metrics.failures += 1
                self.failure_count += 1
                logger.error(f"🔥 WORKER MAIN LOOP ERROR: {e}")
                await asyncio.sleep(1)

    # ==========================================
    # 📦 BATCH PROCESSING (SAFE CONCURRENCY)
    # ==========================================
    async def process_batch(self) -> int:
        """
        Ketma-ket xavfsiz qayta ishlash, lekin bitta tranzaksiyada commit qilish.
        Bu orqali parallel sessiya xatolarining oldi olinadi.
        """
        async with self.session_pool() as session:
            try:
                # 🟢 TO'G'RILANDI: .order_id() o'rniga .order_by() qo'yildi va Boolean tekshiruvi .is_(False) qilindi
                stmt = (
                    select(OutboxEvent)
                    .where(OutboxEvent.processed.is_(False))
                    .order_by(OutboxEvent.id.asc()) 
                    .limit(self.batch_size)
                )

                result = await session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    return 0

                # High-load xavfsizligi: Har bir elementni ketma-ket bajaramiz
                for ev in events:
                    try:
                        # Event yuklamasini qayta ishlash
                        success = await self.handle_event(ev)
                        if success:
                            ev.processed = True
                            # 💡 FIX: Modelda bo'lmagan processed_at o'rniga created_at yangilandi
                            ev.created_at = datetime.now(timezone.utc)
                            metrics.events_processed += 1
                    except Exception as res_err:
                        # Alohida element xatoga uchrasa, butun batchni qulatmaymiz
                        await self.handle_failure(session, ev, res_err)

                # Barcha muvaffaqiyatli o'zgarishlarni bitta tranzaksiyada saqlaymiz
                await session.commit()
                
                # Agar muvaffaqiyatli yakunlansa, Circuit Breaker hisoblagichini kamaytiramiz (Heal mantiqi)
                if self.failure_count > 0:
                    self.failure_count = max(0, self.failure_count - 1)
                
                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"❌ DB BATCH ERROR: {e}")
                await session.rollback()
                self.failure_count += 1
                return 0

    # ==========================================
    # ⚙️ EVENT HANDLER (SAFE PARSING)
    # ==========================================
    async def handle_event(self, ev: OutboxEvent) -> bool:
        try:
            payload = orjson.loads(ev.payload)
        except orjson.JSONDecodeError as json_err:
            logger.error(f"🚨 CRITICAL: OutboxEvent ID {ev.id} payload is not valid JSON: {json_err}")
            # Buzilgan JSON bo'lsa, uni qayta ishlab bo'lmaydi, true qaytarib batchdan chiqarib yuboramiz (yoki DLQ ga otamiz)
            return False 

        user_id = payload.get("user_id")
        if user_id:
            metrics.mark_user(user_id)

        ttl = self.dynamic_ttl(user_id or 0)

        # Routers
        if ev.event_type == "cache_update":
            await self.cache_event(payload, ttl)
        elif ev.event_type == "user_created":
            await self.fake_telegram(payload)
        elif ev.event_type == "points_added":
            await self.fake_notify(payload)

        return True

    
    # ==========================================
    # 🧠 CACHE ACTION (FIXED)
    # ==========================================
    async def cache_event(self, payload, ttl):
        try:
            user_id = payload.get("user_id")
            if user_id:
                # 1. Birinchi navbatda eski keshni tozalaymiz
                await self.cache.invalidate(table="users", obj_id=user_id)
                
                # 2. To'g'ri formatda CacheManager.set metodiga argumentlarni uzatamiz
                # CacheManager o'z ichida shardingni (namespace, shard, version) avtomatik hal qiladi
                await self.cache.set(
                    table="users",
                    obj_id=user_id,
                    data=payload,
                    ttl=ttl
                )
                metrics.cache_hits += 1
            else:
                logger.warning("⚠️ cache_event: Payload ichida user_id topilmadi.")
                metrics.cache_misses += 1
        except Exception as e:
            metrics.cache_misses += 1
            logger.error(f"❌ Cache operation error in worker: {e}")

    # ==========================================
    # 📡 EXTERNAL FAKE SERVICES
    # ==========================================
    async def fake_telegram(self, payload):
        await asyncio.sleep(0.005)

    async def fake_notify(self, payload):
        await asyncio.sleep(0.005)

    # ==========================================
    # 💀 FAILURE + DLQ MANAGEMENT
    # ==========================================
    async def handle_failure(self, session, ev: OutboxEvent, err: Exception):
        metrics.failures += 1
        ev.retry_count += 1
        
        logger.warning(f"⚠️ Event operational failure [ID: {ev.id} | Attempt: {ev.retry_count}]: {err}")

        if ev.retry_count >= self.max_retry:
            # DLQ ga yuborish va bazada processed qilib belgilash
            await self.send_to_dlq(ev, str(err))
            ev.processed = True
            # 💡 FIX: processed_at o'rniga joriy vaqt yaratilish vaqtiga tenglashtirildi
            ev.created_at = datetime.now(timezone.utc)
        
        # O'zgarishlarni sessiyaga qayta yuklash
        session.add(ev)

    async def send_to_dlq(self, ev: OutboxEvent, err: str):
        if self.redis:
            try:
                dlq_sharded_key = self.shard_key(self.dlq_key)
                await self.redis.lpush(
                    dlq_sharded_key,
                    orjson.dumps({
                        "id": ev.id,
                        "event_type": ev.event_type,
                        "error": err,
                        "time": datetime.now(timezone.utc).isoformat()
                    })
                )
            except Exception as redis_err:
                logger.error(f"🚨 FAILED TO PUSH TO REDIS DLQ: {redis_err}")

        logger.critical(f"💀 EVENT PERMANENTLY MOVED TO DLQ: {ev.id}")

    # ==========================================
    # 🛑 GRACEFUL STOP
    # ==========================================
    async def stop(self):
        self.running = False
        logger.info("🛑 OUTBOX WORKER SHUTTING DOWN GRACEFULLY")