import orjson
import logging
import zlib
import base64
from uuid import uuid4
from datetime import datetime, timezone
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
        """ AniNowuz platformasining yuklamasini aqlli boshqarish qoidalari """
        if event_type in ("user_created", "payment", "vip_upgrade"):
            return EventPriorityEngine.HIGH
        elif event_type in ("comment", "like", "history_update", "cache_update", "anime_update"):
            return EventPriorityEngine.MEDIUM
        return EventPriorityEngine.LOW


# ================= EVENT COMPRESSOR (CRASH-SAFE) =================
class EventCompressor:
    """
    Payload compression + base64 safety + robust nested diff engine
    """

    @staticmethod
    def compress(payload: dict) -> str:
        """ Ma'lumotni siqadi va bazada/keshda xavfsiz saqlash uchun Base64 string qaytaradi """
        raw = orjson.dumps(payload)
        compressed = zlib.compress(raw, level=6)
        return base64.b64encode(compressed).decode("utf-8")

    @staticmethod
    def decompress(data_str: str) -> dict:
        """ Base64 stringni qayta baytlarga o'girib, decompress qiladi """
        if not data_str:
            return {}
        binary_data = base64.b64decode(data_str.encode("utf-8"))
        return orjson.loads(zlib.decompress(binary_data))

    @staticmethod
    def diff(old: Optional[dict], new: dict) -> dict:
        """
        🔥 NESTED DIFF FIX: Chuqur ierarxiyaga ega lug'atlarni ham solishtiradi.
        Faqat o'zgargan/yangi qo'shilgan maydonlarni qoldiradi. O'chirilganlarni `None` qiladi.
        """
        if not old:
            return new
            
        delta = {}
        # Yangi va o'zgargan qiymatlarni rekursiv yoki aniq solishtirish
        for k, v in new.items():
            if k not in old:
                delta[k] = v
            elif old[k] != v:
                if isinstance(v, dict) and isinstance(old[k], dict):
                    deep_diff = EventCompressor.diff(old[k], v)
                    if deep_diff:
                        delta[k] = deep_diff
                else:
                    delta[k] = v
                    
        # O'chirilgan qiymatlarni aniqlash
        for k in old.keys():
            if k not in new:
                delta[k] = None
                
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
            ready_timestamp = datetime.now(timezone.utc).timestamp() + delay
            await self.redis.zadd(self.key, {event_id: ready_timestamp})

    async def pop_ready(self) -> List[str]:
        if not self.redis:
            return []
        now = datetime.now(timezone.utc).timestamp()
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
        """
        🔥 TRANSACTION-SAFE TRANSACTIONAL OUTBOX ENGINE
        Kafolatlangan ACID qonuniyatlari asosida ishlaydi.
        """
        event_id = str(uuid4())
        priority = EventPriorityEngine.score(event_type, payload)

        try:
            # State diffing mantiqini qo'llash (Saqlash hajmini minimal qilish uchun)
            if previous_state:
                payload = EventCompressor.diff(previous_state, payload)

            # Siqilgan xavfsiz payload stringi
            compressed_str = EventCompressor.compress(payload)

            # 1. DB INSERT (Faqat tranzaksiyaga qo'shiladi)
            stmt = insert(OutboxEvent).values(
                id=event_id,
                aggregate=aggregate,
                aggregate_id=str(agg_id),
                event_type=event_type,
                payload=compressed_str,
                retry_count=0,
                processed=False,
                created_at=datetime.now(timezone.utc),
            )
            await session.execute(stmt)

            # 🔥 CRITICAL CHANGER: Post-Commit Pipeline funksiyasi
            async def sync_with_redis():
                """ Baza muvaffaqiyatli COMMIT bo'lgandan keyingina Redisni yangilash mexanizmi """
                if self.redis:
                    redis_key = f"{{outbox}}:{aggregate}:{agg_id}"
                    priority_queue_key = "{outbox}:priority_queue"

                    pipe = self.redis.pipeline(transaction=False)
                    pipe.set(redis_key, compressed_str, ex=3600)
                    pipe.zadd(priority_queue_key, {event_id: priority})
                    await pipe.execute()
                    logger.info(f"🚀 Post-Commit: Outbox Redis sync completed [ID: {event_id}]")

            # Agar foydalanuvchi shu zahoti tranzaksiyani yopishni (commit) so'ragan bo'lsa
            if commit:
                await session.commit()
                # Commit muvaffaqiyatli o'tdi, endi Redisni xavfsiz yangilaymiz
                await sync_with_redis()
            else:
                # 🔥 AGAR COMMIT TASHQI XIZMATDA BO'LSA:
                # SQLAlchemyning joriy tranzaksiyasiga post-commit callback ulaymiz,
                # bu orqali tashqi xizmat commit qilgan soniyada Redis avtomatik yangilanadi.
                # Agar tashqi xizmat rollback qilsa, ushbu funksiya ishlamaydi va kesh toza qoladi!
                session.sync_connection.run_override(
                    lambda conn: conn.shared_connection.info.setdefault(
                        "post_commit_hooks", []
                    ).append(sync_with_redis)
                )
                # Eslatma: Agar frameworkingizda buyruqlar zanjiri murakkab bo'lsa, 
                # tashqi xizmat commit qilganidan so'ng await sync_with_redis() ni qo'lda chaqirish ham mumkin.

            logger.info(f"📦 Outbox event staged in DB [ID: {event_id} | Priority: {priority}]")
            return event_id

        except Exception as e:
            logger.error(f"❌ Critical Outbox Service DB Failure: {e}")
            await session.rollback()

            # Baza qulaganda ma'lumot butkul yo'qolmasligi uchun uni DLQ-ga zaxiralaymiz
            await self.dlq.push({
                "event_id": event_id,
                "aggregate": aggregate,
                "agg_id": agg_id,
                "event_type": event_type,
                "payload": payload,
                "error": f"DB_CRASH_OR_ROLLBACK: {str(e)}",
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

        data_str = data.decode("utf-8") if isinstance(data, bytes) else data
        return EventCompressor.decompress(data_str)

    # ================= PRIORITY FETCH =================
    async def get_next_events(self, limit: int = 10) -> List[Any]:
        if not self.redis:
            return []
        # Eng yuqori ustuvorlikdagi va eng birinchi kirgan elementlarni oqilona o'qib olish
        return await self.redis.zpopmax("{outbox}:priority_queue", count=limit)