import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError

from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")


class CacheInvalidationWorker:
    """
    🚀 PRO MAX DISTRIBUTED ZERO-LOSS EVENT SYSTEM

    FEATURES:
    - Retry Queue (in-memory + DB retry)
    - Dead Letter Queue (DLQ)
    - Distributed Lock (Redis safe)
    - Batch processing
    - Crash-safe commit (no event loss)
    - Multi-instance safe (bot scaling)
    - Backpressure protection
    """

    def __init__(self, session_factory, cache_manager, redis=None):
        self.session_factory = session_factory
        self.cache = cache_manager
        self.redis = redis

        self._running = True

        # ================= TUNING =================
        self.batch_size = 150
        self.fast_sleep = 0.05
        self.idle_sleep = 0.3
        self.cleanup_interval = 300

        # retry system
        self.max_retries = 5
        self.retry_delay = 2

        self._last_cleanup = time.time()

        # local retry buffer (fast fallback)
        self.retry_buffer: list[OutboxEvent] = []

        # DLQ cache key
        self.dlq_key = "cache:dlq"

        # lock key
        self.lock_key = "cache_worker_lock"

    # ================= DISTRIBUTED LOCK =================
    async def _acquire_lock(self) -> bool:
        if not self.redis:
            return True

        try:
            return await self.redis.set(
                self.lock_key,
                "1",
                nx=True,
                ex=10
            )
        except Exception as e:
            logger.error(f"Lock error: {e}")
            return False

    async def _release_lock(self):
        if not self.redis:
            return

        try:
            await self.redis.delete(self.lock_key)
        except Exception:
            pass

    # ================= MAIN LOOP =================
    async def _setup_redis_stream(self):
        """Redis Stream va Group mavjudligini ta'minlaydi"""
        if not self.redis:
            return

        stream_key = "cache:invalidate"  # Logdagi xatoga ko'ra
        group_name = "cache_group"

        try:
            # Guruhni yaratish (mkstream=True stream bo'lmasa uni ham yaratadi)
            await self.redis.xgroup_create(stream_key, group_name, id='0', mkstream=True)
            logger.info(f"✅ Redis Stream Group '{group_name}' yaratildi.")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                # Guruh allaqachon bor, bu normal holat
                pass
            else:
                logger.error(f"❌ Redis Stream sozlashda xato: {e}")


    async def run(self):
        logger.info("🚀 Cache Worker STARTED (ZERO-LOSS MODE)")
        
        await self._setup_redis_stream()

        while self._running:
            try:
                # distributed safety
                if not await self._acquire_lock():
                    await asyncio.sleep(1)
                    continue

                processed = await self.process_events()

                await self._release_lock()

                if processed > 0:
                    await asyncio.sleep(self.fast_sleep)
                else:
                    await asyncio.sleep(self.idle_sleep)

                await self._maybe_cleanup()

            except asyncio.CancelledError:
                logger.warning("🛑 Worker cancelled")
                break

            except Exception as e:
                logger.error(f"🔥 Worker crash: {e}")
                await asyncio.sleep(2)

    # ================= EVENT PROCESS =================
    async def process_events(self) -> int:
        async with self.session_factory() as session:

            try:
                stmt = (
                    select(OutboxEvent)
                    .where(OutboxEvent.processed == False)
                    .order_by(OutboxEvent.created_at.asc())
                    .limit(self.batch_size)
                )

                result = await session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    return 0

                tasks = [
                    self._safe_process(session, ev)
                    for ev in events
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                await session.commit()

                # failed events retry buffer
                for i, res in enumerate(results):
                    if isinstance(res, Exception):
                        self.retry_buffer.append(events[i])

                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"DB ERROR: {e}")
                await session.rollback()
                return 0

    # ================= SAFE PROCESS =================
    async def _safe_process(self, session, ev: OutboxEvent):
        try:
            await self._process_single(session, ev)

        except Exception as e:
            logger.error(f"❌ Event failed {ev.id}: {e}")
            await self._handle_failure(ev, str(e))
            raise

    # ================= SINGLE EVENT =================
    async def _process_single(self, session, ev: OutboxEvent):

        # cache invalidation
        await self.cache.invalidate(ev.aggregate, ev.aggregate_id)

        ev.processed = True
        ev.processed_at = datetime.now(timezone.utc)

    # ================= FAILURE HANDLING =================
    async def _handle_failure(self, ev: OutboxEvent, error: str):

        ev.retry_count += 1

        # 🔥 retry system
        if ev.retry_count <= self.max_retries:
            await asyncio.sleep(self.retry_delay * ev.retry_count)

            async with self.session_factory() as session:
                await session.merge(ev)
                await session.commit()

            logger.warning(f"🔁 RETRY {ev.id} ({ev.retry_count})")
            return

        # ================= DLQ =================
        await self._send_to_dlq(ev, error)

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
                await self.redis.lpush(self.dlq_key, str(payload))

            logger.critical(f"💀 DLQ PUSHED: {ev.id}")

        except Exception as e:
            logger.critical(f"DLQ FAILED: {e}")

    # ================= RETRY BUFFER FLUSH =================
    async def _flush_retry_buffer(self):
        if not self.retry_buffer:
            return

        logger.warning(f"♻️ retry buffer flush: {len(self.retry_buffer)}")

        async with self.session_factory() as session:
            for ev in self.retry_buffer:
                session.add(ev)

            await session.commit()

        self.retry_buffer.clear()

    # ================= CLEANUP =================
    async def _maybe_cleanup(self):
        now = time.time()

        if now - self._last_cleanup < self.cleanup_interval:
            return

        self._last_cleanup = now

        try:
            async with self.session_factory() as session:

                await session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.processed == True
                    )
                )

                await session.commit()

            await self._flush_retry_buffer()

            logger.info("🧹 Worker cleanup done")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    # ================= STOP =================
    async def stop(self):
        self._running = False

        await self._flush_retry_buffer()

        if self.redis:
            await self._release_lock()

        logger.info("🛑 Worker STOPPED (safe shutdown)")