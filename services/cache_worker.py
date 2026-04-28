import asyncio
import logging
from sqlalchemy import select, delete
from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")

class CacheInvalidationWorker:
    def __init__(self, session_factory, cache_manager):
        # session_factory — bu async_sessionmaker bo'lishi kerak
        self.session_factory = session_factory
        self.cache = cache_manager
        self._running = True

    async def run(self):
        logger.info("🚀 Cache Invalidation Worker: ACTIVE")
        while self._running:
            try:
                processed_count = await self.process_events()
                # Agar eventlar bo'lsa tezroq ishlaymiz, bo'lmasa dam olamiz
                sleep_time = 0.1 if processed_count > 0 else 0.5
                await asyncio.sleep(sleep_time)
            except Exception as e:
                logger.error(f"Worker Loop Error: {e}")
                await asyncio.sleep(5)

    async def process_events(self) -> int:
        async with self.session_factory() as session:
            # 1. Qayta ishlanmagan xabarlarni SQLAlchemy 2.0 style'da olish
            stmt = select(OutboxEvent).filter_by(processed=False).limit(100)
            result = await session.execute(stmt)
            events = result.scalars().all()
            
            if not events:
                return 0

            for ev in events:
                try:
                    # 2. Redis Stream orqali barcha node'larga xabar yuborish
                    # Bu metod CacheManager'da Redis'ga XADD qiladi
                    await self.cache.invalidate(ev.aggregate, ev.aggregate_id)
                    ev.processed = True
                except Exception as e:
                    logger.error(f"Invalidation failed for {ev.aggregate}:{ev.aggregate_id}: {e}")

            # 3. Batch commit
            await session.commit()
            
            # 4. Eski xabarlarni o'chirish (Vaqti-vaqti bilan qilish tavsiya etiladi)
            # Masalan, processed_count ma'lum songa yetganda yoki random
            return len(events)

    async def cleanup_old_events(self):
        """Eski (processed) xabarlarni ommaviy o'chirish."""
        async with self.session_factory() as session:
            await session.execute(delete(OutboxEvent).where(OutboxEvent.processed == True))
            await session.commit()
            logger.info("🧹 Outbox cleanup completed.")

    def stop(self):
        self._running = False