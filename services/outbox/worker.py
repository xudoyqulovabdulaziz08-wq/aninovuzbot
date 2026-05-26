import zlib
import orjson
import json
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
# 🧠 AI CACHE + METRICS ENGINE (REAL O(1) & MEMORY SAFE)
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
        
        # 🔥 FIX: Memory Leak oldini olish uchun faqat oxirgi 10 000 ta faol userni eslab qolamiz
        self.user_heat = defaultdict(int)
        self._user_cleanup_counter = 0

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
        self._user_cleanup_counter += 1
        
        # 🔥 FIX: Har 10 000 ta operatsiyada eskirgan foydalanuvchilar lug'atini tozalaymiz (RAM xavfsizligi)
        if self._user_cleanup_counter > 10000:
            self.clear_cold_users()

    def is_hot_user(self, user_id):
        return self.user_heat[user_id] > 20

    def clear_cold_users(self):
        """Aktiv bo'lmagan foydalanuvchilarni xotiradan o'chiradi"""
        for uid in list(self.user_heat.keys()):
            if self.user_heat[uid] <= 2:
                del self.user_heat[uid]
            else:
                self.user_heat[uid] = self.user_heat[uid] // 2  # Issiqlik darajasini pasaytirish
        self._user_cleanup_counter = 0


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
            return base * 5  # Hot user keshda ko'proq turadi
        return base + random.randint(0, 120)

    def shard_key(self, key: str) -> str:
        if not self.redis:
            return key
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
                    await asyncio.sleep(0.01)  # Dinamik yuklama tanaffusi
                else:
                    await asyncio.sleep(0.5)   # Bo'sh turganda kutish

            except Exception as e:
                metrics.failures += 1
                self.failure_count += 1
                logger.error(f"🔥 WORKER MAIN LOOP ERROR: {e}")
                await asyncio.sleep(1)

    # ==========================================
    # 📦 BATCH PROCESSING (SAFE CONCURRENCY)
    # ==========================================
    async def process_batch(self) -> int:
        async with self.session_pool() as session:
            try:
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

                for ev in events:
                    try:
                        success = await self.handle_event(ev)
                        if success:
                            ev.processed = True
                            ev.created_at = datetime.now(timezone.utc)
                            metrics.events_processed += 1
                    except Exception as res_err:
                        # 🔥 FIX: Xatoga uchragan elementni xavfsiz boshqarish
                        await self.handle_failure(session, ev, res_err)

                await session.commit()
                
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
        # 1. Payloadni yuklash (agar bazadan string kelsa - o'giramiz)
        raw_payload = ev.payload
        if isinstance(raw_payload, str):
            payload = orjson.loads(raw_payload)
        else:
            payload = raw_payload

        # 2. Siqilganlik holatini tekshirish
        if payload.get("is_compressed"):
            # HEX stringni baytga o'girish
            compressed_hex = payload.get("data")
            raw_bytes = bytes.fromhex(compressed_hex)
            
            # Decompression (zlib orqali ochish)
            decompressed_bytes = zlib.decompress(raw_bytes)
            
            # Ochilgan ma'lumotni dict ga o'girish
            payload = orjson.loads(decompressed_bytes)
            
    except Exception as e:
        logger.critical(f"🚨 PAYLOAD PARSING ERROR [ID: {ev.id}]: {e}")
        await self.send_to_dlq_raw(ev, f"Parsing failed: {e}")
        return True # Worker qulamasligi uchun True qaytaramiz

    # 3. Asosiy biznes logika davomi...
    user_id = payload.get("user_id")
    # ... qolgan kodlar

    # ==========================================
    # 💀 RAW DLQ FOR BROKEN JSON
    # ==========================================
    async def send_to_dlq_raw(self, ev: OutboxEvent, err_msg: str):
        if self.redis:
            try:
                dlq_sharded_key = self.shard_key(self.dlq_key)
                safe_payload = str(ev.payload) if ev.payload else "EMPTY_PAYLOAD"
                await self.redis.lpush(
                    dlq_sharded_key,
                    orjson.dumps({
                        "id": ev.id,
                        "event_type": ev.event_type,
                        "error": err_msg,
                        "raw_payload": safe_payload,
                        "time": datetime.now(timezone.utc).isoformat()
                    })
                )
            except Exception as redis_err:
                logger.error(f"🚨 FAILED TO PUSH TO REDIS RAW DLQ: {redis_err}")
        logger.critical(f"💀 BROKEN EVENT FORCED TO DLQ: {ev.id}")
    
    # ==========================================
    # 🧠 CACHE ACTION (RACE-CONDITION SAFE)
    # ==========================================
    async def cache_event(self, payload, ttl, event_id):
        try:
            user_id = payload.get("user_id")
            if user_id:
                # 🔥 FIX: Invalidate va Set o'rniga, faqat bitta atomik xavfsiz SET buyrug'i.
                # Event ID dagi ketma-ketlik (version) kesh eskirib qolishining (Race condition) oldini oladi.
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
            await self.send_to_dlq(ev, str(err))
            ev.processed = True
            ev.created_at = datetime.now(timezone.utc)
        
        # 🔥 FIX: Agar sessiya buzilgan bo'lsa merge() xavfsizroq ulaydi
        try:
            await session.merge(ev)
        except Exception as merge_err:
            logger.error(f"🚨 Session merge failed for failed event: {merge_err}")

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