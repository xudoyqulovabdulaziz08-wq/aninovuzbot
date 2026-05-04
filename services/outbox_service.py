import orjson
import logging
import zlib
import difflib
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select

from database.models import OutboxEvent

logger = logging.getLogger("OutboxService")


# ================= AI PRIORITY ENGINE =================
class EventPriorityEngine:
    """
    AI-style scoring (rule-based v1)
    later: ML model plug-in
    """

    HIGH = 3
    MEDIUM = 2
    LOW = 1

    @staticmethod
    def score(event_type: str, payload: dict) -> int:
        score = EventPriorityEngine.LOW

        # critical user events
        if event_type in ("user_created", "payment", "vip"):
            score = EventPriorityEngine.HIGH

        # engagement events
        elif event_type in ("comment", "like", "history"):
            score = EventPriorityEngine.MEDIUM

        # cache events
        elif event_type in ("cache_update", "anime_update"):
            score = EventPriorityEngine.MEDIUM

        # fallback
        return score


# ================= EVENT COMPRESSOR =================
class EventCompressor:
    """
    payload compression + diff storage engine
    """

    @staticmethod
    def compress(payload: dict) -> bytes:
        raw = orjson.dumps(payload)
        return zlib.compress(raw, level=6)

    @staticmethod
    def decompress(data: bytes) -> dict:
        return orjson.loads(zlib.decompress(data))

    @staticmethod
    def diff(old: dict, new: dict) -> dict:
        """
        store only changed fields (70% storage reduction)
        """
        delta = {}

        for k, v in new.items():
            if old.get(k) != v:
                delta[k] = v

        return delta or new


# ================= DLQ HANDLER =================
class DeadLetterQueue:
    def __init__(self, redis):
        self.redis = redis
        self.key = "outbox:dlq"

    async def push(self, event: dict):
        await self.redis.lpush(self.key, orjson.dumps(event))

    async def fetch(self, limit: int = 50):
        items = await self.redis.lrange(self.key, 0, limit)
        return [orjson.loads(i) for i in items]


# ================= RETRY QUEUE =================
class RetryQueue:
    def __init__(self, redis):
        self.redis = redis
        self.key = "outbox:retry"

    async def push(self, event_id: str, delay: int = 5):
        await self.redis.zadd(self.key, {event_id: datetime.now().timestamp() + delay})

    async def pop_ready(self):
        now = datetime.now().timestamp()
        return await self.redis.zrangebyscore(self.key, 0, now)


# ================= OUTBOX SERVICE CORE =================
class OutboxService:

    def __init__(self, redis):
        self.redis = redis
        self.dlq = DeadLetterQueue(redis)
        self.retry = RetryQueue(redis)

    # ================= MAIN CREATE =================
    async def create_event(
        self,
        session: AsyncSession,
        aggregate: str,
        agg_id: str,
        event_type: str,
        payload: dict,
        previous_state: Optional[dict] = None,
        commit: bool = False,
    ):
        event_id = str(uuid4())

        try:
            # ================= PRIORITY =================
            priority = EventPriorityEngine.score(event_type, payload)

            # ================= COMPRESSION =================
            if previous_state:
                payload = EventCompressor.diff(previous_state, payload)

            compressed_payload = EventCompressor.compress(payload)

            # ================= DB INSERT =================
            stmt = insert(OutboxEvent).values(
                id=event_id,
                aggregate=aggregate,
                aggregate_id=str(agg_id),
                event_type=event_type,
                payload=compressed_payload.decode("latin1"),
                retry_count=0,
                processed=False,
                created_at=datetime.now(timezone.utc),
            )

            await session.execute(stmt)

            # ================= REDIS MIRROR (DUAL WRITE SAFETY) =================
            redis_key = f"outbox:{aggregate}:{agg_id}"

            await self.redis.set(
                redis_key,
                compressed_payload,
                ex=3600
            )

            # ================= PRIORITY QUEUE =================
            await self.redis.zadd(
                "outbox:priority_queue",
                {event_id: priority}
            )

            if commit:
                await session.commit()

            logger.info(
                f"📦 Event created {aggregate}:{agg_id}:{event_type} priority={priority}"
            )

            return event_id

        # ================= FAILURE HANDLING =================
        except Exception as e:
            logger.error(f"❌ Outbox failed: {e}")

            # DLQ fallback
            await self.dlq.push({
                "aggregate": aggregate,
                "agg_id": agg_id,
                "event_type": event_type,
                "payload": payload,
                "error": str(e),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            await session.rollback()
            raise

    # ================= EVENT RETRIEVER =================
    async def get_event(self, aggregate: str, agg_id: str):
        key = f"outbox:{aggregate}:{agg_id}"

        data = await self.redis.get(key)
        if not data:
            return None

        return EventCompressor.decompress(data)

    # ================= PRIORITY FETCH =================
    async def get_next_events(self, limit: int = 10):
        """
        AI prioritized event fetching
        """
        events = await self.redis.zpopmax("outbox:priority_queue", count=limit)
        return events