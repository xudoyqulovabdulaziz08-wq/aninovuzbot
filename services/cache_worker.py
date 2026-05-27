import os
import uuid
import time
import asyncio
import logging
import orjson
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from sqlalchemy import select, delete, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")


class CacheInvalidationWorker:
    """
    🚀 PRO MAX DISTRIBUTED ZERO-LOSS EVENT SYSTEM
    🛠 INTEGRATED: Valkey Dual-Layer Invalidation, Parallel Batch Invalidation, and Seamless Cleanups.
    """

    def __init__(self, session_factory: Any, cache_manager: Any, redis: Optional[Any] = None):
        self.session_factory = session_factory
        self.cache = cache_manager  # Valkey L1 + L2 cache manager proxy
        self.redis = redis

        self._running = True
        self.instance_id = str(uuid.uuid4())

        # ================= TUNING =================
        self.batch_size = 150
        self.fast_sleep = 0.05
        self.idle_sleep = 0.5
        self.cleanup_interval = 300  # 5 daqiqa

        self.max_retries = 5
        self._last_cleanup = time.time()

        self.dlq_key = "cache:dlq"
        self.lock_key = "cache_worker_lock"
        self.stream_key = "cache:invalidate"

    # ================= DISTRIBUTED LOCK =================
    async def _acquire_lock(self) -> bool:
        if not self.redis:
            return True
        try:
            # Ko'p instansiyali muhitda bir xil eventlarni ikki marta qayta ishlamaslik uchun lock
            return await self.redis.set(
                self.lock_key,
                self.instance_id,
                nx=True,
                ex=30  # 30 soniyalik TTL xavfsiz avto-tark etish uchun
            )
        except Exception as e:
            logger.error(f"❌ Lock acquire error: {e}")
            return False

    async def _release_lock(self):
        if not self.redis:
            return
        try:
            lua_release = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            await self.redis.eval(lua_release, 1, self.lock_key, self.instance_id)
        except Exception as e:
            logger.debug(f"Lock release error: {e}")

    # ================= REDIS STREAM SETUP =================
    async def _setup_redis_stream(self):
        if not self.redis:
            return
        group_name = "cache_group"
        try:
            await self.redis.xgroup_create(self.stream_key, group_name, id='0', mkstream=True)
            logger.info(f"✅ Redis/Valkey Stream Group '{group_name}' verified.")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"❌ Redis Stream setup error: {e}")

    # ================= MAIN LOOP =================
    async def run(self):
        logger.info(f"🚀 Cache Worker STARTED [Instance ID: {self.instance_id}] (ZERO-LOSS & MULTI-INSTANCE SAFE)")
        await self._setup_redis_stream()

        while self._running:
            try:
                if not await self._acquire_lock():
                    # Agar boshqa node ishlayotgan bo'lsa, kutamiz
                    await asyncio.sleep(1.0)
                    continue

                processed = await self.process_events()
                await self._release_lock()

                if processed > 0:
                    await asyncio.sleep(self.fast_sleep)
                else:
                    await asyncio.sleep(self.idle_sleep)

                # Davriy ravishda eskirgan va muvaffaqiyatli o'tgan eventlarni o'chirish
                await self._maybe_cleanup()

            except asyncio.CancelledError:
                logger.warning("🛑 Worker execution cancelled by orchestrator")
                break
            except Exception as e:
                logger.error(f"🔥 Worker unexpected loop crash: {e}")
                await self._release_lock()
                await asyncio.sleep(2)

    # ================= EVENT PROCESS (PARALLELIZED) =================
    async def process_events(self) -> int:
        async with self.session_factory() as session:
            try:
                now = datetime.now(timezone.utc)
                
                stmt = (
                    select(OutboxEvent)
                    .where(
                        and_(
                            OutboxEvent.processed.is_(False),
                            or_(
                                OutboxEvent.created_at.is_(None),
                                OutboxEvent.created_at <= now
                            )
                        )
                    )
                    .order_by(OutboxEvent.created_at.asc())
                    .limit(self.batch_size)
                )

                result = await session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    return 0

                # Guruh ichidagi har bir elementni parallel qayta ishlash uchun mantiq
                async def safe_process_single(ev: OutboxEvent):
                    try:
                        await self._process_single(ev)
                    except Exception as e:
                        logger.error(f"❌ Event execution failed [ID: {ev.id}]: {e}")
                        await self._handle_failure(session, ev, str(e))

                # 🔥 CRITICAL OPTIMIZATION: Ketma-ketlik o'rniga parallel asyncio.gather
                await asyncio.gather(*(safe_process_single(ev) for ev in events))

                # Batch yakunida barcha o'zgarishlarni bitta tranzaksiyada saqlaymiz
                await session.commit()
                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"❌ Database execution error in cache batch: {e}")
                await session.rollback()
                return 0

    # ================= SINGLE EVENT PROCESS (FIXED & BROADCASTED) =================
    async def _process_single(self, ev: OutboxEvent):
        """
        🔥 DUAL-LAYER CACHE FIX:
        Keshni shunchaki joriy worker xotirasidan emas, balki loyihangiz kesh menejeri orqali 
        global miqyosda (L1 local + L2 Valkey va boshqa barcha parallel server node-larida) o'chiramiz.
        """
        # 1. Mahalliy node keshini o'chirish va L2 (Valkey) keshni tozalash
        await self.cache.invalidate(table=ev.aggregate, obj_id=ev.aggregate_id)
        
        # 2. Parallel ishlayotgan boshqa serverlardagi (L1) keshni ham o'chirishini so'rab Streamga signal berish
        if self.redis:
            await self.redis.xadd(
                self.stream_key,
                {
                    "action": "invalidate",
                    "table": str(ev.aggregate),
                    "obj_id": str(ev.aggregate_id),
                    "sender": self.instance_id
                }
            )
        
        ev.processed = True
        ev.created_at = datetime.now(timezone.utc)

    # ================= FAILURE HANDLING (EXPONENTIAL BACKOFF) =================
    async def _handle_failure(self, session: Any, ev: OutboxEvent, error: str):
        ev.retry_count += 1

        if ev.retry_count <= self.max_retries:
            # Eksponentsial ortib boruvchi kutish vaqti (5s, 10s, 15s...)
            delay_seconds = 5 * ev.retry_count
            ev.created_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            
            logger.warning(f"🔁 Event [ID: {ev.id}] scheduled for retry {ev.retry_count}/{self.max_retries} in {delay_seconds}s")
            await session.merge(ev)
            return

        # Maksimal urinishlar soni tugasa elementni DLQ xavfsiz hududiga otamiz
        await self._send_to_dlq(ev, error)
        ev.processed = True
        ev.created_at = datetime.now(timezone.utc)
        await session.merge(ev)

    # ================= DEAD LETTER QUEUE =================
    async def _send_to_dlq(self, ev: OutboxEvent, error: str):
        try:
            payload = {
                "id": ev.id,
                "aggregate": ev.aggregate,
                "aggregate_id": ev.aggregate_id,
                "error": error,
                "retry_count": ev.retry_count,
                "time": datetime.now(timezone.utc).isoformat()
            }

            if self.redis:
                await self.redis.lpush(self.dlq_key, orjson.dumps(payload))

            logger.critical(f"💀 EVENT PERMANENTLY MOVED TO DLQ: {ev.id} | Cause: {error}")

        except Exception as e:
            logger.critical(f"🚨 CRITICAL: Failed to push to DLQ stream: {e}")

    # ================= CLEANUP OLD PROCESSED EVENTS =================
    async def _maybe_cleanup(self):
        """ Muvaffaqiyatli bajarilgan eski outbox xabarlarini tozalash (Storage Optimization) """
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return

        self._last_cleanup = now
        try:
            async with self.session_factory() as session:
                # 🔥 CRITICAL FIX: IN operatori o'rniga to'g'ridan-to'g'ri bitta so'rovda tozalash (RAM va DB uchun yengil)
                stmt = delete(OutboxEvent).where(OutboxEvent.processed.is_(True))
                result = await session.execute(stmt)
                await session.commit()
                
                if result.rowcount > 0:
                    logger.info(f"🧹 Storage cleaned: {result.rowcount} processed cache events purged from database.")
        except Exception as e:
            logger.error(f"❌ Cleanup storage error: {e}")

    # ================= GRACEFUL STOP =================
    async def stop(self):
        self._running = False
        if self.redis:
            await self._release_lock()
        logger.info("🛑 Cache Invalidation Worker SHUTDOWN GRACEFULLY")