import asyncio
import logging
import time
import random
from datetime import datetime, timezone
from collections import defaultdict, deque

import orjson
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.models import OutboxEvent

logger = logging.getLogger("PRO_WORKER")


# ==============================
# 🧠 AI CACHE + METRICS ENGINE
# ==============================
class MetricsBrain:
    def __init__(self):
        self.cache_hits = 0
        self.cache_misses = 0
        self.db_calls = 0
        self.events_processed = 0
        self.failures = 0

        self.latency_window = deque(maxlen=200)
        self.user_heat = defaultdict(int)  # hot user detection

    # ---------- cache ratio ----------
    def cache_ratio(self):
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total) * 100 if total else 0

    # ---------- latency ----------
    def add_latency(self, value):
        self.latency_window.append(value)

    def avg_latency(self):
        return sum(self.latency_window) / len(self.latency_window) if self.latency_window else 0

    # ---------- hot user detection ----------
    def mark_user(self, user_id):
        self.user_heat[user_id] += 1

    def is_hot_user(self, user_id):
        return self.user_heat[user_id] > 20


metrics = MetricsBrain()


# ==============================
# 🚀 PRO ULTRA WORKER
# ==============================
class OutboxWorker:
    def __init__(self, session_pool, cache_manager, redis=None):
        self.session_pool = session_pool
        self.cache = cache_manager
        self.redis = redis

        self.running = True

        # tuning
        self.batch_size = 80
        self.max_retry = 6
        self.parallel_limit = 20

        # DLQ
        self.dlq_key = "dlq:outbox"

        # circuit breaker
        self.failure_threshold = 10
        self.failure_count = 0
        self.circuit_open = False
        self.last_fail_time = 0

    # ==============================
    # 🔥 AI TTL ENGINE
    # ==============================
    def dynamic_ttl(self, user_id: int) -> int:
        base = 300

        if metrics.is_hot_user(user_id):
            return base * 5  # hot user cache longer

        return base + random.randint(0, 120)

    # ==============================
    # 🌍 SHARD ROUTING (Redis Cluster READY)
    # ==============================
    def shard_key(self, key: str) -> str:
        if not self.redis:
            return key

        shard = hash(key) % 3
        return f"shard:{shard}:{key}"

    # ==============================
    # 🚨 CIRCUIT BREAKER
    # ==============================
    def check_circuit(self):
        if self.failure_count >= self.failure_threshold:
            self.circuit_open = True
            self.last_fail_time = time.time()
            logger.warning("⚠️ CIRCUIT OPENED")

        if self.circuit_open and time.time() - self.last_fail_time > 30:
            self.circuit_open = False
            self.failure_count = 0
            logger.info("✅ CIRCUIT CLOSED")

    # ==============================
    # 🚀 MAIN LOOP
    # ==============================
    async def start(self):
        logger.info("🚀 PRO ULTRA WORKER STARTED")

        while self.running:
            try:
                self.check_circuit()

                if self.circuit_open:
                    await asyncio.sleep(2)
                    continue

                start = time.time()

                processed = await self.process_batch()

                metrics.add_latency(time.time() - start)

                if processed:
                    await asyncio.sleep(0.1)
                else:
                    await asyncio.sleep(0.8)

            except Exception as e:
                metrics.failures += 1
                self.failure_count += 1
                logger.error(f"🔥 WORKER ERROR: {e}")
                await asyncio.sleep(1)

    # ==============================
    # 📦 BATCH PROCESSING
    # ==============================
    async def process_batch(self):
        async with self.session_pool() as session:

            try:
                stmt = (
                    select(OutboxEvent)
                    .where(OutboxEvent.processed == False)
                    .limit(self.batch_size)
                )

                result = await session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    return 0

                semaphore = asyncio.Semaphore(self.parallel_limit)

                async def runner(ev):
                    async with semaphore:
                        return await self.handle_event(session, ev)

                tasks = [runner(ev) for ev in events]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for ev, res in zip(events, results):
                    if isinstance(res, Exception):
                        await self.handle_failure(ev, res)
                    else:
                        ev.processed = True
                        ev.processed_at = datetime.now(timezone.utc)
                        metrics.events_processed += 1

                await session.commit()
                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"DB ERROR: {e}")
                await session.rollback()
                return 0

    # ==============================
    # ⚙️ EVENT HANDLER
    # ==============================
    async def handle_event(self, session, ev: OutboxEvent):

        payload = orjson.loads(ev.payload)

        user_id = payload.get("user_id")
        if user_id:
            metrics.mark_user(user_id)

        # cache brain decision
        ttl = self.dynamic_ttl(user_id or 0)

        # route event
        if ev.event_type == "cache_update":
            await self.cache_event(payload, ttl)

        elif ev.event_type == "user_created":
            await self.fake_telegram(payload)

        elif ev.event_type == "points_added":
            await self.fake_notify(payload)

        return True

    # ==============================
    # 🧠 CACHE BRAIN ACTION
    # ==============================
    async def cache_event(self, payload, ttl):
        try:
            user_id = payload.get("user_id")

            if user_id:
                self.cache.invalidate("users", user_id)

            await self.cache.set(
                "users",
                user_id,
                payload,
                ttl=ttl
            )

            metrics.cache_hits += 1

        except Exception as e:
            metrics.cache_misses += 1
            logger.error(f"Cache error: {e}")

    # ==============================
    # 📡 FAKE SERVICES
    # ==============================
    async def fake_telegram(self, payload):
        await asyncio.sleep(0.01)

    async def fake_notify(self, payload):
        await asyncio.sleep(0.01)

    # ==============================
    # 💀 FAILURE + DLQ
    # ==============================
    async def handle_failure(self, ev, err):

        metrics.failures += 1

        ev.retry_count += 1

        if ev.retry_count >= self.max_retry:
            await self.send_to_dlq(ev, str(err))
            ev.processed = True

    async def send_to_dlq(self, ev, err):
        if self.redis:
            await self.redis.lpush(
                self.dlq_key,
                orjson.dumps({
                    "id": ev.id,
                    "error": str(err),
                    "time": datetime.now(timezone.utc).isoformat()
                })
            )

        logger.critical(f"💀 DLQ: {ev.id}")

    # ==============================
    # 🛑 STOP
    # ==============================
    async def stop(self):
        self.running = False
        logger.info("🛑 WORKER STOPPED")