import time
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")


class CacheInvalidationWorker:
    def __init__(self, session_factory, cache_manager):
        self.session_factory = session_factory
        self.cache = cache_manager

        self._running = True

        # tuning (production optimized)
        self.batch_size = 100
        self.fast_sleep = 0.1
        self.idle_sleep = 0.5
        self.cleanup_interval = 300  # 5 min

        self._last_cleanup = time.time()

    # ================= MAIN LOOP =================
    async def run(self):
        logger.info("🚀 Cache Invalidation Worker STARTED")

        while self._running:
            try:
                processed = await self.process_events()

                # adaptive sleep (load-based)
                if processed > 0:
                    await asyncio.sleep(self.fast_sleep)
                else:
                    await asyncio.sleep(self.idle_sleep)

                # periodic cleanup
                await self._maybe_cleanup()

            except asyncio.CancelledError:
                logger.warning("🛑 Worker cancelled")
                break

            except Exception as e:
                logger.error(f"🔥 Worker loop error: {e}")
                await asyncio.sleep(3)

    # ================= EVENT PROCESS =================
    async def process_events(self) -> int:
        async with self.session_factory() as session:

            # 🔥 batch fetch (FAST)
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

            # ================= PARALLEL INVALIDATION =================
            tasks = []
            for ev in events:
                tasks.append(self._process_single(session, ev))

            await asyncio.gather(*tasks, return_exceptions=True)

            await session.commit()

            return len(events)

    # ================= SINGLE EVENT =================
    async def _process_single(self, session, ev: OutboxEvent):
        try:
            # 🔥 REAL CACHE INVALIDATION
            await self.cache.invalidate(ev.aggregate, ev.aggregate_id)

            ev.processed = True
            ev.processed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(
                f"❌ Invalidation failed {ev.aggregate}:{ev.aggregate_id} -> {e}"
            )

    # ================= CLEANUP =================
    async def _maybe_cleanup(self):
        now = time.time()

        if now - self._last_cleanup < self.cleanup_interval:
            return

        self._last_cleanup = now

        try:
            async with self.session_factory() as session:
                await session.execute(
                    delete(OutboxEvent).where(OutboxEvent.processed == True)
                )
                await session.commit()

            logger.info("🧹 Outbox cleanup done")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    # ================= STOP =================
    def stop(self):
        self._running = False
        logger.info("🛑 Cache Worker STOPPED")