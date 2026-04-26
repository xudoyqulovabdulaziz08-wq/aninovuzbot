import asyncio
import logging
from sqlalchemy.orm import Session
from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")

class CacheInvalidationWorker:
    def __init__(self, session_factory, cache_manager):
        self.session_factory = session_factory
        self.cache = cache_manager
        self._running = True

    async def run(self):
        logger.info("🚀 Cache Invalidation Worker started...")
        while self._running:
            try:
                await self.process_events()
                await asyncio.sleep(0.5) # Polling tezligi
            except Exception as e:
                logger.error(f"Worker Loop Error: {e}")
                await asyncio.sleep(5)

    async def process_events(self):
        with self.session_factory() as session:
            # 1. Qayta ishlanmagan xabarlarni olish
            events = session.query(OutboxEvent).filter_by(processed=False).limit(50).all()
            if not events: return

            for ev in events:
                try:
                    # 2. Keshni tozalash (Distributed Invalidation)
                    await self.cache.invalidate(ev.aggregate, ev.aggregate_id)
                    ev.processed = True
                except Exception as e:
                    logger.error(f"Failed to invalidate {ev.aggregate}:{ev.aggregate_id}: {e}")

            # 3. Batch commit - xabarlarni o'chirilgan deb belgilash
            session.commit()
            
            # 4. Tozalash (Optional): Eski xabarlarni DB'dan o'chirish
            session.query(OutboxEvent).filter_by(processed=True).delete()
            session.commit()

    def stop(self):
        self._running = False