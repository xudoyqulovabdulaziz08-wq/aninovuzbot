import asyncio
import logging
import orjson
from datetime import datetime, timezone

from sqlalchemy import select

from database.models import OutboxEvent

logger = logging.getLogger("OutboxWorker")


class OutboxWorker:
    def __init__(self, session_pool):
        self.session_pool = session_pool
        self.running = True

        self.batch_size = 20
        self.sleep_time = 2
        self.max_retry = 5

    # ================= START =================
    async def start(self):
        logger.info("🚀 Outbox Worker STARTED")

        while self.running:
            try:
                await self.process_batch()
                await asyncio.sleep(self.sleep_time)

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(3)

    # ================= BATCH =================
    async def process_batch(self):
        async with self.session_pool() as session:

            stmt = (
                select(OutboxEvent)
                .where(OutboxEvent.processed == False)
                .order_by(OutboxEvent.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(self.batch_size)
            )

            result = await session.execute(stmt)
            events = result.scalars().all()

            if not events:
                return

            for event in events:
                await self.handle_event(session, event)

            await session.commit()

    # ================= EVENT HANDLER =================
    async def handle_event(self, session, event: OutboxEvent):
        try:
            payload = orjson.loads(event.payload)

            # ===== ROUTER =====
            if event.event_type == "user_created":
                await self.send_telegram_message(payload)

            elif event.event_type == "points_added":
                await self.notify_user(payload)

            # 🔥 CACHE INVALIDATION / UPDATE SIGNAL
            elif event.event_type in ("update", "cache_update", "anime_update"):

                # circular import avoid (IMPORTANT)
                from services.orchestrator import state

                await self.push_cache_update(payload, state)

            # ===== SUCCESS =====
            event.processed = True
            event.processed_at = datetime.now(timezone.utc)

        except Exception as e:
            event.retry_count += 1
            logger.error(f"Event failed {event.id}: {e}")

            if event.retry_count >= self.max_retry:
                event.processed = True
                event.processed_at = datetime.now(timezone.utc)
                logger.warning(f"Dead event archived: {event.id}")

    # ================= CACHE PUSH (FAST PATH) =================
    async def push_cache_update(self, payload, state):
        """
        L1 cache invalidate/update trigger (FAST PATH)
        """
        try:
            user_id = payload.get("user_id")
            if user_id:
                state.l1_cache.pop(user_id, None)

            # queue orqali orchestrator update qiladi
            await state.cache_queue.put(payload)

        except Exception as e:
            logger.error(f"Cache push failed: {e}")

    # ================= DISPATCHERS =================
    async def send_telegram_message(self, payload):
        print("📨 send message:", payload)

    async def notify_user(self, payload):
        print("🔔 notify:", payload)

    # ================= STOP =================
    async def stop(self):
        self.running = False
        logger.info("🛑 Outbox Worker STOPPED")