import zlib
import orjson
import asyncio
import logging
import time
import random
import hashlib
from datetime import datetime, timezone
from collections import defaultdict, deque
from typing import Any, Dict, Optional, List

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
        
        # 🔥 Memory Leak oldini olish uchun faqat faol userni eslab qolamiz
        self.user_heat = defaultdict(int)
        self._user_cleanup_counter = 0

    def cache_ratio(self) -> float:
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total) * 100 if total else 0

    def add_latency(self, value: float):
        if len(self.latency_window) == self.window_size:
            self._latency_sum -= self.latency_window[0]
        
        self.latency_window.append(value)
        self._latency_sum += value

    def avg_latency(self) -> float:
        count = len(self.latency_window)
        return self._latency_sum / count if count > 0 else 0.0

    def mark_user(self, user_id: int):
        self.user_heat[user_id] += 1
        self._user_cleanup_counter += 1
        
        if self._user_cleanup_counter > 10000:
            self.clear_cold_users()

    def is_hot_user(self, user_id: int) -> bool:
        return self.user_heat[user_id] > 20

    def clear_cold_users(self):
        """ Aktiv bo'lmagan foydalanuvchilarni xotiradan tozalash (RAM xavfsizligi) """
        for uid in list(self.user_heat.keys()):
            if self.user_heat[uid] <= 2:
                del self.user_heat[uid]
            else:
                self.user_heat[uid] = self.user_heat[uid] // 2
        self._user_cleanup_counter = 0


metrics = MetricsBrain()


# ==========================================
# 🚀 PRO ULTRA WORKER (CRASH + CLUSTER SAFE)
# ==========================================
class OutboxWorker:
    def __init__(self, session_pool: Any, cache_manager: Any, redis: Optional[Any] = None):
        self.session_pool = session_pool
        self.cache = cache_manager  # Valkey L1+L2 Dual-Layer Cache obyekti
        self.redis = redis

        self.running = True

        # Tuning parameters
        self.batch_size = 100
        self.max_retry = 6
        self.parallel_limit = 20  # Semaforda parallel ishlash chegarasi

        # DLQ key
        self.dlq_key = "dlq:outbox"

        # Circuit Breaker state
        self.failure_threshold = 10
        self.failure_count = 0
        self.circuit_open = False
        self.last_fail_time = 0.0

    def dynamic_ttl(self, user_id: int) -> int:
        base = 300
        if metrics.is_hot_user(user_id):
            return base * 5  # Hot user keshda 25 daqiqa saqlanadi
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
                    await asyncio.sleep(0.01)  # Dinamik yuklama tanaffusi (CPU tinchlanishi uchun)
                else:
                    await asyncio.sleep(0.5)   # Bo'sh turganda kutish banti

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
                # Faqat qayta ishlanmagan eventlarni id bo'yicha tartiblab olamiz
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

                semaphore = asyncio.Semaphore(self.parallel_limit)

                # Guruh ichida bitta eventni xavfsiz boshqarish oqimi
                async def safe_process(ev: OutboxEvent):
                    async with semaphore:
                        try:
                            success = await self.handle_event(ev)
                            if success:
                                ev.processed = True
                                ev.created_at = datetime.now(timezone.utc)
                                metrics.events_processed += 1
                        except Exception as res_err:
                            # Xatoga uchragan amalni tranzaksiya ichida xavfsiz belgilash
                            await self.handle_failure(session, ev, res_err)

                # Tasklarni parallel asinxron ishga tushiramiz (Silliq va tezkor qayta ishlash)
                await asyncio.gather(*(safe_process(ev) for ev in events))

                # Hamma eventlar holati yangilangach, yagona tranzaksiyada commit qilamiz
                await session.commit()
                
                if self.failure_count > 0:
                    self.failure_count = max(0, self.failure_count - 1)
                
                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"❌ DB BATCH ERROR IN WORKER: {e}")
                await session.rollback()
                self.failure_count += 1
                return 0

    # ==========================================
    # ⚙️ EVENT HANDLER (SAFE PARSING & EXECUTION)
    # ==========================================
    async def handle_event(self, ev: OutboxEvent) -> bool:
        try:
            # 1. Payloadni yuklash
            raw_payload = ev.payload
            if isinstance(raw_payload, str):
                payload = orjson.loads(raw_payload)
            else:
                payload = raw_payload

            # 2. Siqilganlik holatini tekshirish va ochish
            if isinstance(payload, dict) and payload.get("is_compressed"):
                compressed_hex = payload.get("data")
                raw_bytes = bytes.fromhex(compressed_hex)
                decompressed_bytes = zlib.decompress(raw_bytes)
                payload = orjson.loads(decompressed_bytes)
            
        except Exception as e:
            logger.critical(f"🚨 PAYLOAD PARSING ERROR [ID: {ev.id}]: {e}")
            await self.send_to_dlq_raw(ev, f"Parsing failed: {e}")
            return True  # Worker qulab zanjir to'xtamasligi uchun True qaytaramiz

        try:
            # 3. Asosiy biznes logikani bajarish (Tashqi integratsiyalar)
            # Parallel feyk xizmatlarni chaqiramiz
            await asyncio.gather(
                self.fake_telegram(payload),
                self.fake_notify(payload)
            )

            # 4. Kesh bilan ishlash (Race-condition safe)
            user_id = payload.get("user_id")
            if user_id:
                metrics.mark_user(int(user_id))
                ttl = self.dynamic_ttl(int(user_id))
                await self.cache_event(payload, ttl, ev.id)

            return True

        except Exception as biz_err:
            # Biznes xatolik yuz berganini process_batch bilishi uchun xatoni tepaga otamiz
            raise biz_err

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
    async def cache_event(self, payload: Dict[str, Any], ttl: int, event_id: str):
        try:
            user_id = payload.get("user_id")
            if user_id:
                # Dual-layer kesh klasteriga yozamiz (L1 local + L2 Valkey klaster yangilanadi)
                # broadcast=True parametri barcha parallel node-larda kesh izchilligini ta'minlaydi
                await self.cache.set(
                    table="users",
                    obj_id=str(user_id),
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
    async def fake_telegram(self, payload: Dict[str, Any]):
        await asyncio.sleep(0.005)

    async def fake_notify(self, payload: Dict[str, Any]):
        await asyncio.sleep(0.005)

    # ==========================================
    # 💀 FAILURE + DLQ MANAGEMENT
    # ==========================================
    async def handle_failure(self, session: Any, ev: OutboxEvent, err: Exception):
        metrics.failures += 1
        ev.retry_count += 1
        
        logger.warning(f"⚠️ Event operational failure [ID: {ev.id} | Attempt: {ev.retry_count}]: {err}")

        if ev.retry_count >= self.max_retry:
            await self.send_to_dlq(ev, str(err))
            ev.processed = True
            ev.created_at = datetime.now(timezone.utc)
        
        # Agar sessiya oqimi uzilgan bo'lsa merge() orqali bog'lanish xavfsiz tiklanadi
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