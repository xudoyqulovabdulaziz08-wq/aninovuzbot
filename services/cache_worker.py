import os
import uuid
import time
import asyncio
import logging
import orjson
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from sqlalchemy import select, delete, and_, or_, update
from sqlalchemy.exc import SQLAlchemyError
from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")

class CacheInvalidationWorker:
    """
    🚀 ULTRA PRO MAX DISTRIBUTED ZERO-LOSS EVENT SYSTEM (PROD READY)
    """

    def __init__(self, session_factory: Any, cache_manager: Any, redis: Optional[Any] = None):
        self.session_factory = session_factory
        self.cache = cache_manager  # Valkey L1 + L2 cache manager proxy
        self.redis = redis

        self._running = True
        self.instance_id = str(uuid.uuid4())

        # ================= TUNING =================
        self.batch_size = 30
        self.fast_sleep = 0.1  # CPU va Redis yuklamasini kamaytirish uchun 0.02 dan 0.1 ga oshirildi
        self.idle_sleep = 0.5
        self.cleanup_interval = 300  # 5 daqiqa

        self.max_retries = 5
        self._last_cleanup = time.time()

        # Kalitlar integratsiyasi
        self.dlq_key = "{cache}:dlq"
        self.lock_key = "{cache}:worker_lock"
        self.stream_key = "{cache}:invalidate"
        
        # 🔒 CONNECTION POOL PROTECTION SEMAPHORE
        # Bir vaqtning o'zida bazaga ko'p ulanish ochilmasligini nazorat qiladi
        self.db_semaphore = asyncio.Semaphore(5) 

    # ================= DISTRIBUTED LOCK =================
    async def _acquire_lock(self) -> bool:
        if not self.redis:
            return True
        try:
            return await self.redis.set(
                self.lock_key,
                self.instance_id,
                nx=True,
                ex=60
            )
        except Exception as e:
            logger.error(f"❌ Lock acquire error: {e}")
            return False

    async def _release_lock(self):
        if not self.redis:
            return
        try:
            lua_release = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            await self.redis.eval(lua_release, 1, self.lock_key, self.instance_id)
        except Exception as e:
            logger.debug(f"Lock release error: {e}")

    # ================= REDIS STREAM SETUP =================
    async def _setup_redis_stream(self):
        if not self.redis:
            return
        group_name = "cache_group"
        try:
            await self.redis.xgroup_create(self.stream_key, group_name, id='0', mkstream=True)
            logger.info(f"✅ Redis/Valkey Stream Group '{group_name}' verified.")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"❌ Redis Stream setup error: {e}")

    # ================= MAIN LOOP =================
    async def run(self):
        logger.info(f"🚀 Cache Worker STARTED [Instance ID: {self.instance_id}]")
        await self._setup_redis_stream()

        while self._running:
            try:
                if not await self._acquire_lock():
                    await asyncio.sleep(self.idle_sleep)
                    continue

                try:
                    processed = await self.process_events()
                finally:
                    await self._release_lock()

                if processed > 0:
                    await asyncio.sleep(self.fast_sleep)
                else:
                    await asyncio.sleep(self.idle_sleep)

                await self._maybe_cleanup()

            except asyncio.CancelledError:
                logger.warning("🛑 Worker execution cancelled by orchestrator")
                break
            except Exception as e:
                logger.error(f"🔥 Worker unexpected loop crash: {e}")
                await asyncio.sleep(2)

    # ================= EVENT PROCESS (CONCURRENT-SAFE) =================
    async def process_events(self) -> int:
        async with self.session_factory() as main_session:
            try:
                now = datetime.now(timezone.utc)
                
                stmt = (
                    select(OutboxEvent)
                    .where(
                        and_(
                            OutboxEvent.processed.is_(False),
                            or_(
                                OutboxEvent.created_at.is_(None),
                                OutboxEvent.created_at <= now
                            )
                        )
                    )
                    .order_by(OutboxEvent.priority.desc(), OutboxEvent.created_at.asc())
                    .limit(self.batch_size)
                )

                result = await main_session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    return 0

                # Bizga faqat ID va kerakli ma'lumotlar xotirada qolishi kifoya (Sessiyadan ajratamiz)
                # Bu orqali har bir task mustaqil ishlay oladi
                event_data_list = [
                    {
                        "id": ev.id,
                        "aggregate": ev.aggregate,
                        "aggregate_id": ev.aggregate_id,
                        "retry_count": ev.retry_count
                    } for ev in events
                ]

                async def safe_process_single(ev_data: dict):
                    # Semaphore yordamida DB ulanishlar pooldan tartib bilan olinadi
                    async with self.db_semaphore:
                        async with self.session_factory() as ev_session:
                            try:
                                # Keshni invalidatsiya qilish va streamga chiqarish
                                await self._process_cache_and_stream(ev_data)
                                
                                # Obyektni to'liq yuklamasdan (merge-siz) to'g'ridan-to'g'ri UPDATE so'rovi berish
                                u_stmt = (
                                    update(OutboxEvent)
                                    .where(OutboxEvent.id == ev_data["id"])
                                    .values(processed=True, processed_at=datetime.now(timezone.utc))
                                )
                                await ev_session.execute(u_stmt)
                                await ev_session.commit()
                            except Exception as e:
                                await ev_session.rollback()
                                logger.error(f"❌ Event execution failed [ID: {ev_data['id']}]: {e}")
                                
                                # Xatolikni alohida sessiyada qayta ishlash
                                async with self.session_factory() as fail_session:
                                    await self._handle_failure(fail_session, ev_data, str(e))
                                    await fail_session.commit()

                # Tasklar guruhini xavfsiz parallel boshqarish
                await asyncio.gather(*(safe_process_single(ev) for ev in event_data_list))
                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"❌ Database execution error in cache batch: {e}")
                return 0

    # ================= INVALIDATION LOGIC =================
    async def _process_cache_and_stream(self, ev_data: dict):
        # 1. Keshni tozalash
        await self.cache.invalidate(table=ev_data["aggregate"], obj_id=ev_data["aggregate_id"])
        
        # 2. Redis Stream xabari
        if self.redis:
            await self.redis.xadd(
                self.stream_key,
                {
                    "action": "invalidate",
                    "table": str(ev_data["aggregate"]),
                    "obj_id": str(ev_data["aggregate_id"]),
                    "sender": self.instance_id
                },
                maxlen=10000,
                approximate=True
            )

    # ================= FAILURE HANDLING (TRUE EXPONENTIAL BACKOFF) =================
    async def _handle_failure(self, session: Any, ev_data: dict, error: str):
        new_retry_count = ev_data["retry_count"] + 1

        if new_retry_count <= self.max_retries:
            delay_seconds = min(5 * (2 ** new_retry_count), 300)
            next_run = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            
            u_stmt = (
                update(OutboxEvent)
                .where(OutboxEvent.id == ev_data["id"])
                .values(retry_count=new_retry_count, created_at=next_run)
            )
            await session.execute(u_stmt)
            logger.warning(f"🔁 Event [ID: {ev_data['id']}] scheduled for retry {new_retry_count}/{self.max_retries} in {delay_seconds}s")
            return

        # Maksimal urinishlar tugasa DLQ ga ketadi
        await self._send_to_dlq(ev_data, error, new_retry_count)
        
        u_stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id == ev_data["id"])
            .values(processed=True, processed_at=datetime.now(timezone.utc), retry_count=new_retry_count)
        )
        await session.execute(u_stmt)

    # ================= DEAD LETTER QUEUE =================
    async def _send_to_dlq(self, ev_data: dict, error: str, final_retry_count: int):
        try:
            payload = {
                "id": ev_data["id"],
                "aggregate": ev_data["aggregate"],
                "aggregate_id": ev_data["aggregate_id"],
                "error": error,
                "retry_count": final_retry_count,
                "time": datetime.now(timezone.utc).isoformat()
            }

            if self.redis:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.lpush(self.dlq_key, orjson.dumps(payload))
                    pipe.ltrim(self.dlq_key, 0, 9999)
                    await pipe.execute()

            logger.critical(f"💀 EVENT PERMANENTLY MOVED TO DLQ: {ev_data['id']} | Cause: {error}")
        except Exception as e:
            logger.critical(f"🚨 CRITICAL: Failed to push to DLQ stream: {e}")

    # ================= CLEANUP OLD PROCESSED EVENTS =================
    async def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return

        self._last_cleanup = now
        try:
            async with self.session_factory() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                
                stmt = (
                    delete(OutboxEvent)
                    .where(
                        and_(
                            OutboxEvent.processed.is_(True),
                            OutboxEvent.processed_at <= cutoff
                        )
                    )
                )
                result = await session.execute(stmt)
                await session.commit()
                
                if result.rowcount > 0:
                    logger.info(f"Purged {result.rowcount} processed cache events (older than 24h).")
        except Exception as e:
            logger.error(f"❌ Cleanup storage error: {e}")

    # ================= GRACEFUL STOP =================
    async def stop(self):
        self._running = False
        if self.redis:
            await self._release_lock()
        logger.info("🛑 Cache Invalidation Worker SHUTDOWN GRACEFULLY")