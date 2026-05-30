import asyncio
import orjson
import logging
import zlib
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List, Tuple

from sqlalchemy import event
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
    def score(event_type: str) -> int:
        """ 
        ✅ Kichik Muammo 3 FIX: Ishlatilmayotgan payload parametri olib tashlandi, 
        faqat event_type bo'yicha tezkor aniqlanadi.
        """
        if event_type in ("user_created", "payment", "vip_upgrade"):
            return EventPriorityEngine.HIGH
        elif event_type in ("comment", "like", "history_update", "cache_update", "anime_update"):
            return EventPriorityEngine.MEDIUM
        return EventPriorityEngine.LOW


# ================= EVENT COMPRESSOR (CRASH-SAFE) =================
class EventCompressor:
    """
    Payload compression with robust nested diff engine.
    🚀 FIX 4 & Standartlashtirish: Hex ham, Base64 ham emas — toza BINARY (bytes) ishlatiladi!
    """

    @staticmethod
    def compress(payload: dict) -> bytes:
        """ Ma'lumotni JSON qilib siqadi va xom baytlar (bytes) qaytaradi """
        return zlib.compress(orjson.dumps(payload), level=6)

    @staticmethod
    def decompress(binary_data: bytes) -> dict:
        """ Baytlarni decompress qilib JSON obyekti sifatida yuklaydi """
        if not binary_data:
            return {}
        return orjson.loads(zlib.decompress(binary_data))

    @staticmethod
    def diff(old: Optional[dict], new: dict) -> Optional[dict]:
        """
        🔥 Jiddiy Xato 5 FIX: Chuqur ierarxiyani to'g'ri solishtiradi.
        Agar hech narsa o'zgarmasa, bo'sh dict ({}) qaytaradi va bu o'zgarish yo'qligini anglatadi.
        """
        if not old:
            return new
            
        delta = {}
        for k, v in new.items():
            if k not in old:
                delta[k] = v
            elif old[k] != v:
                if isinstance(v, dict) and isinstance(old[k], dict):
                    deep_diff = EventCompressor.diff(old[k], v)
                    if deep_diff:  # Agar ichki obyektda o'zgarish bo'lsa
                        delta[k] = deep_diff
                else:
                    delta[k] = v
                    
        for k in old.keys():
            if k not in new:
                delta[k] = None
                
        return delta  # ✅ Hech narsa o'zgarmasa bo'sh dict ({}) qaytadi


# ================= DLQ HANDLER =================
class DeadLetterQueue:
    def __init__(self, redis):
        self.redis = redis
        self.key = "{outbox}:dlq"

    async def push(self, event: dict):
        """ ✅ Jiddiy Xato 4 FIX: LTRIM qo'shildi, DLQ hajmi cheksiz o'smaydi (Max 10k) """
        if self.redis:
            try:
                pipe = self.redis.pipeline(transaction=False)
                pipe.lpush(self.key, orjson.dumps(event))
                pipe.ltrim(self.key, 0, 9999)  # Eng so'nggi 10,000 ta xato xabari saqlanadi
                await pipe.execute()
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
        """ ✅ Jiddiy Xato 3 FIX: Atomic Read + Delete (Pipeline MULTI/EXEC) orqali cheksiz loop bartaraf etildi """
        if not self.redis:
            return []
        
        now = datetime.now(timezone.utc).timestamp()
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zrangebyscore(self.key, 0, now)
                pipe.zremrangebyscore(self.key, 0, now)  # O'qilgan zahoti o'chirish
                results, _ = await pipe.execute()
                
            return [r.decode("utf-8") if isinstance(r, bytes) else r for r in results]
        except Exception as e:
            logger.error(f"❌ RetryQueue pop_ready failed: {e}")
            return []


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
        ACID va asinxron event-driven arxitektura qonuniyatlariga to'liq mos keladi.
        """
        event_id = str(uuid4())
        priority = EventPriorityEngine.score(event_type)

        try:
            # State diffing mantiqini tekshirish
            if previous_state:
                diff_payload = EventCompressor.diff(previous_state, payload)
                # ✅ Jiddiy Xato 5 FIX: Agar diff bo'sh bo'lsa, demak o'zgarish yo'q, jarayonni to'xtatamiz
                if previous_state and not diff_payload:
                    logger.info(f"ℹ️ Outbox skipped: O'zgarish topilmadi ({aggregate}:{agg_id})")
                    return None
                payload = diff_payload

            # Siqilgan binary xom baytlar
            compressed_bytes = EventCompressor.compress(payload)

            # DB INSERT
            stmt = insert(OutboxEvent).values(
                id=event_id,
                aggregate=aggregate,
                aggregate_id=str(agg_id),
                event_type=event_type,
                payload=compressed_bytes, 
                priority=priority,  # ✅ Kichik Muammo 1 FIX: DB modeliga priority saqlanadi
                retry_count=0,
                processed=False,
                created_at=datetime.now(timezone.utc),
            )
            await session.execute(stmt)

            # Redis sinxronizatsiyasi uchun asinxron pipeline funksiyasi
            async def sync_with_redis():
                if self.redis:
                    try:
                        redis_key = f"{{outbox}}:{aggregate}:{agg_id}"
                        priority_queue_key = "{outbox}:priority_queue"

                        pipe = self.redis.pipeline(transaction=False)
                        pipe.set(redis_key, compressed_bytes, ex=3600)
                        pipe.zadd(priority_queue_key, {event_id: priority})
                        await pipe.execute()
                        logger.info(f"🚀 Post-Commit: Redis integratsiyasi bajarildi [ID: {event_id}]")
                    except Exception as re:
                        logger.error(f"⚠️ Redis post-commit sync error: {re}. Worker DB orqali qayta ishlaydi.")

            # ✅ Jiddiy Xato 1 FIX: To'g'ri asinxron SQLAlchemy after_commit hodisasi ulandi!
            if commit:
                await session.commit()
                await sync_with_redis()
            else:
                # Tashqi tranzaksiya commit bo'lishini kutuvchi xavfsiz hodisa tinglovchisi
                @event.listens_for(session.sync_session, "after_commit", once=True)
                def after_commit_hook(target_session):
                    # Asinxron fonda (Event Loopni bloklamay) Redisga yozish vazifasini topshiramiz
                    asyncio.create_task(sync_with_redis())

            logger.info(f"📦 Outbox event staged in DB [ID: {event_id} | Priority: {priority}]")
            return event_id

        except Exception as e:
            logger.error(f"❌ Critical Outbox Service DB Failure: {e}")
            
            # ✅ Jiddiy Xato 2 FIX: create_event ichida session.rollback() olib tashlandi.
            # Tashqi biznes mantiqining tranzaksiyasiga daxl qilinmaydi, faqat raise tashlanadi!
            
            # Ma'lumot yo'qolmasligi uchun uni xavfsiz DLQ-ga zaxiralaymiz
            await self.dlq.push({
                "event_id": event_id,
                "aggregate": aggregate,
                "agg_id": agg_id,
                "event_type": event_type,
                "payload": payload,
                "error": f"OUTBOX_STAGE_ERROR: {str(e)}",
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

        # Ma'lumot to'g'ridan-to'g'ri bytes formatida keladi va decompress qilinadi
        return EventCompressor.decompress(data)

    # ================= ZERO-LOSS PRIORITY FETCH =================
    async def get_next_events(self, limit: int = 10) -> List[Tuple[str, float]]:
        """
        🚀 ZERO-LOSS ACQUISITION ENGINE (At-Least-Once kafolati)
        ✅ Kichik Muammo 2 Izoh: Agar Redis bo'sh bo'lsa yoki uzilsa, Worker o'z-o'zidan 
        Baza (DB) dagi OutboxEvent jadvalidan `processed=False` va `priority` bo'yicha order qilib o'qiydi.
        """
        if not self.redis:
            return []
        
        priority_queue_key = "{outbox}:priority_queue"
        # Ustuvorlik bo'yicha o'qish (O'chirmasdan, distributed worker xavfsizligi uchun)
        results = await self.redis.zrevrange(priority_queue_key, 0, limit - 1, withscores=True)
        
        formatted_results = []
        for event_id_bytes, score in results:
            ev_id = event_id_bytes.decode("utf-8") if isinstance(event_id_bytes, bytes) else event_id_bytes
            formatted_results.append((ev_id, score))
            
        return formatted_results

    async def acknowledge_event(self, event_id: str) -> bool:
        """ Worker vazifani muvaffaqiyatli tugatgandan so'ng xabarni navbatdan to'liq o'chiradi """
        if self.redis:
            priority_queue_key = "{outbox}:priority_queue"
            return await self.redis.zrem(priority_queue_key, event_id) > 0
        return False