import asyncio
import logging
import orjson
from datetime import datetime, timezone

from sqlalchemy import select, update


from database.models import OutboxEvent  # 🔥 FIX

logger = logging.getLogger("OutboxWorker")


class OutboxWorker:
    def __init__(self, session_pool):
        self.session_pool = session_pool
        self.running = True

    async def start(self):
        while self.running:
            try:
                await self.process_batch()
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(3)

    async def process_batch(self):
        async with self.session_pool() as session:

            # 🔥 LOCKED CLAIM (important fix)
            stmt = (
                select(OutboxEvent)
                .where(OutboxEvent.processed == False)
                .with_for_update(skip_locked=True)  # 💣 critical fix
                .limit(20)
            )

            result = await session.execute(stmt)
            events = result.scalars().all()

            for event in events:
                await self.handle_event(session, event)

            await session.commit()

    async def handle_event(self, session, event: OutboxEvent):
        try:
            payload = orjson.loads(event.payload)

            # ===== DISPATCH LOGIC =====
            if event.event_type == "user_created":
                await self.send_telegram_message(payload)

            elif event.event_type == "points_added":
                await self.notify_user(payload)

            # mark processed
            event.processed = True
            event.processed_at = datetime.now(timezone.utc)

        except Exception as e:
            event.retry_count += 1
            logger.error(f"Event failed {event.id}: {e}")

            if event.retry_count > 5:
                event.processed = True
                event.processed_at = datetime.now(timezone.utc)

    async def send_telegram_message(self, payload):
        print("send message:", payload)

    async def notify_user(self, payload):
        print("notify:", payload)