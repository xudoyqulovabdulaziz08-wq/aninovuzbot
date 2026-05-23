import orjson
import logging
import zlib
import base64
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from database.models import OutboxEvent

logger = logging.getLogger("OutboxService")


# ================= AI PRIORITY ENGINE =================
class EventPriorityEngine:
    HIGH = 3
    MEDIUM = 2
    LOW = 1

    @staticmethod
    def score(event_type: str, payload: dict) -> int:
        # Aninowuz platformasi uchun ustuvorlik qoidalari
        if event_type in ("user_created", "payment", "vip_upgrade"):
            return EventPriorityEngine.HIGH
        elif event_type in ("comment", "like", "history_update"):
            return EventPriorityEngine.MEDIUM
        elif event_type in ("cache_update", "anime_update"):
            return EventPriorityEngine.MEDIUM
        return EventPriorityEngine.LOW


# ================= EVENT COMPRESSOR (CRASH-SAFE) =================
class EventCompressor:
    """
    Payload compression + base64 safety + stable diff engine
    """

    @staticmethod
    def compress(payload: dict) -> str:
        """Ma'lumotni siqadi va bazada/keshda xavfsiz saqlash uchun Base64 string qaytaradi"""
        raw = orjson.dumps(payload)
        compressed = zlib.compress(raw, level=6)
        return base64.b64encode(compressed).decode("utf-8")

    @staticmethod
    def decompress(data_str: str) -> dict:
        """Base64 stringni qayta baytlarga o'girib, decompress qiladi"""
        if not data_str:
            return {}
        binary_data = base64.b64decode(data_str.encode("utf-8"))
        return orjson.loads(zlib.decompress(binary_data))

    @staticmethod
    def diff(old: Optional[dict], new: dict) -> dict:
        """
        Faqat o'zgargan va yangi qo'shilgan maydonlarni hisoblaydi (Storage Reduction).
        O'chirilgan maydonlarni ham `None` sifatida belgilaydi.
        """
        if not old:
            return new
            
        delta = {}
        # Yangi va o'zgargan qiymatlar
        for k, v in new.items():
            if old.get(k) != v:
                delta[k] = v
                
        # O'chirilgan qiymatlarni aniqlash
        for k in old.keys():
            if k not in new:
                delta[k] = None  # Maydon o'chirilganini bildiradi
                
        return delta if delta else new


# ================= DLQ HANDLER =================
class DeadLetterQueue:
    def __init__(self, redis):
        self.redis = redis
        self.key = "{outbox}:dlq"

    async def push(self, event: dict):
        if self.redis:
            try:
                await self.redis.lpush(self.key, orjson.dumps(event))
            except Exception as e:
                logger.critical(f"🚨 FAILED TO WRITE TO DLQ REDIS: {e}")

    async def fetch(self, limit: int = 50) -> List[dict]:
        if not self.redis:
            return []
        items = await self.redis.lrange(self.key, 0, limit - 1)
        return [orjson.loads(i) for i in items]


# ================= RETRY QUEUE =================
class RetryQueue:
    def __init__(self, redis):
        self.redis = redis
        self.key = "{outbox}:retry"

    async def push(self, event_id: str, delay: int = 5):
        if self.redis:
            # Haqiqiy UTC timestamp xatoliksiz ishlashni kafolatlaydi
            ready_timestamp = datetime.now(timezone.utc).timestamp() + delay
            await self.redis.zadd(self.key, {event_id: ready_timestamp})

    async def pop_ready(self) -> List[str]:
        if not self.redis:
            return []
        now = datetime.now(timezone.utc).timestamp()
        # Byte matnlarni string ko'rinishida qaytarish
        results = await self.redis.zrangebyscore(self.key, 0, now)
        return [r.decode("utf-8") if isinstance(r, bytes) else r for r in results]


# ================= OUTBOX SERVICE CORE =================
class OutboxService:
    def __init__(self, redis):
        self.redis = redis
        self.dlq = DeadLetterQueue(redis)
        self.retry = RetryQueue(redis)

    async def create_event(
        self,
        session: AsyncSession,
        aggregate: str,
        agg_id: str,
        event_type: str,
        payload: dict,
        previous_state: Optional[dict] = None,
        commit: bool = False,
    ) -> Optional[str]:
        event_id = str(uuid4())
        
        try:
            priority = EventPriorityEngine.score(event_type, payload)

            # State diffing mantiqini qo'llash
            if previous_state:
                payload = EventCompressor.diff(previous_state, payload)

            # Siqilgan va Base64 qilingan xavfsiz string saqlash
            compressed_str = EventCompressor.compress(payload)

            # 1. DB INSERT (Faqat SQL bajariladi, lekin commit qilinmaydi)
            stmt = insert(OutboxEvent).values(
                id=event_id,
                aggregate=aggregate,
                aggregate_id=str(agg_id),
                event_type=event_type,
                payload=compressed_str,  # Safe base64 payload
                retry_count=0,
                processed=False,
                created_at=datetime.now(timezone.utc),
            )
            await session.execute(stmt)

            # Agar foydalanuvchi darhol commit qilishni so'ragan bo'lsa
            if commit:
                await session.commit()

            # 2. POST-COMMIT / TRANSACTION SAFETY
            # Kesh va Queue faqat ma'lumot bazaga muvaffaqiyatli yozilsa yangilanadi
            if self.redis:
                # Redis Cluster mosligi uchun Hash Tag formatlash `{outbox}`
                redis_key = f"{{outbox}}:{aggregate}:{agg_id}"
                priority_queue_key = "{outbox}:priority_queue"

                # Pipeline orqali Redis atomikligini oshirish
                pipe = self.redis.pipeline(transaction=False)
                pipe.set(redis_key, compressed_str, ex=3600)
                pipe.zadd(priority_queue_key, {event_id: priority})
                await pipe.execute()

            logger.info(f"📦 Outbox event registered [ID: {event_id} | Priority: {priority}]")
            return event_id

        except Exception as e:
            logger.error(f"❌ Critical Outbox Service Failure: {e}")
            
            # Tranzaksiyani bekor qilish (Rollback)
            await session.rollback()

            # Baza qulagan bo'lsa ham voqea yo'qolmasligi uchun DLQ-ga saqlab qolamiz
            await self.dlq.push({
                "event_id": event_id,
                "aggregate": aggregate,
                "agg_id": agg_id,
                "event_type": event_type,
                "payload": payload,
                "error": str(e),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            raise

    # ================= EVENT RETRIEVER =================
    async def get_event(self, aggregate: str, agg_id: str) -> Optional[dict]:
        if not self.redis:
            return None
            
        key = f"{{outbox}}:{aggregate}:{agg_id}"
        data = await self.redis.get(key)
        
        if not data:
            return None

        # Agar ma'lumot keshdan bytes holatda kelsa stringga o'tkazamiz
        data_str = data.decode("utf-8") if isinstance(data, bytes) else data
        return EventCompressor.decompress(data_str)

    # ================= PRIORITY FETCH =================
    async def get_next_events(self, limit: int = 10) -> List[Any]:
        if not self.redis:
            return []
        # Eng yuqori ustuvorlikdagi elementlarni o'qib olish
        events = await self.redis.zpopmax("{outbox}:priority_queue", count=limit)
        return events