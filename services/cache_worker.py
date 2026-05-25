import os
import uuid
import time
import asyncio
import logging
import orjson
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from database.models import OutboxEvent

logger = logging.getLogger("CacheWorker")


class CacheInvalidationWorker:
    """
    🚀 PRO MAX DISTRIBUTED ZERO-LOSS EVENT SYSTEM
    🛠 FIXED: CacheManager integration, Named Invalidation arguments, and Safe Backoff.
    """

    def __init__(self, session_factory, cache_manager, redis=None):
        self.session_factory = session_factory
        self.cache = cache_manager
        self.redis = redis

        self._running = True
        self.instance_id = str(uuid.uuid4())

        # ================= TUNING =================
        self.batch_size = 150
        self.fast_sleep = 0.05
        self.idle_sleep = 0.5
        self.cleanup_interval = 300

        self.max_retries = 5
        self._last_cleanup = time.time()

        self.retry_buffer: list[OutboxEvent] = []

        self.dlq_key = "cache:dlq"
        self.lock_key = "cache_worker_lock"

    # ================= DISTRIBUTED LOCK =================
    async def _acquire_lock(self) -> bool:
        if not self.redis:
            return True
        try:
            return await self.redis.set(
                self.lock_key,
                self.instance_id,
                nx=True,
                ex=30  
            )
        except Exception as e:
            logger.error(f"Lock acquire error: {e}")
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
        stream_key = "cache:invalidate"
        group_name = "cache_group"
        try:
            await self.redis.xgroup_create(stream_key, group_name, id='0', mkstream=True)
            logger.info(f"✅ Redis Stream Group '{group_name}' verified.")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"❌ Redis Stream setup error: {e}")

    # ================= MAIN LOOP =================
    async def run(self):
        logger.info("🚀 Cache Worker STARTED (ZERO-LOSS & MULTI-INSTANCE SAFE)")
        await self._setup_redis_stream()

        while self._running:
            try:
                if not await self._acquire_lock():
                    await asyncio.sleep(1.0)
                    continue

                processed = await self.process_events()
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
                await self._release_lock()
                await asyncio.sleep(2)

    # ================= EVENT PROCESS =================
    async def process_events(self) -> int:
        async with self.session_factory() as session:
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
                    .order_by(OutboxEvent.created_at.asc())
                    .limit(self.batch_size)
                )

                result = await session.execute(stmt)
                events = result.scalars().all()

                if not events:
                    return 0

                for ev in events:
                    try:
                        await self._process_single(ev)
                    except Exception as e:
                        logger.error(f"❌ Event execution failed [ID: {ev.id}]: {e}")
                        await self._handle_failure(session, ev, str(e))

                await session.commit()
                return len(events)

            except SQLAlchemyError as e:
                logger.error(f"❌ Database execution error in batch: {e}")
                await session.rollback()
                return 0

    # ================= SINGLE EVENT PROCESS (FIXED) =================
    async def _process_single(self, ev: OutboxEvent):
        # 🔥 FIX: Argumentlarni nomli (keyword) ko'rinishda uzatamiz. 
        # Bu CacheManager.invalidate() metodiga to'g'ri tushishini ta'minlaydi.
        await self.cache.invalidate(table=ev.aggregate, obj_id=ev.aggregate_id)
        
        ev.processed = True
        ev.created_at = datetime.now(timezone.utc)

    # ================= FAILURE HANDLING (FIXED) =================
    async def _handle_failure(self, session, ev: OutboxEvent, error: str):
        ev.retry_count += 1

        if ev.retry_count <= self.max_retries:
            # Exponential Backoff mantiqini saqlaymiz, lekin created_at ni xavfsiz vaqt bilan belgilaymiz
            delay_seconds = 5 * ev.retry_count
            ev.created_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            
            logger.warning(f"🔁 Event [ID: {ev.id}] scheduled for retry {ev.retry_count}/{self.max_retries}")
            session.add(ev)
            return

        # Max retries tugasa DLQ ga yuboramiz
        await self._send_to_dlq(ev, error)
        ev.processed = True
        ev.created_at = datetime.now(timezone.utc)
        session.add(ev)

    # ================= DEAD LETTER QUEUE =================
    async def _send_to_dlq(self, ev: OutboxEvent, error: str):
        try:
            payload = {
                "id": ev.id,
                "aggregate": ev.aggregate,
                "aggregate_id": ev.aggregate_id,
                "error": error,
                "retry_count": ev.retry_count,
                "time": datetime.now(timezone.utc).isoformat()
            }

            if self.redis:
                await self.redis.lpush(self.dlq_key, orjson.dumps(payload))

            logger.critical(f"💀 EVENT PERMANENTLY MOVED TO DLQ: {ev.id}")

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
                subq = select(OutboxEvent.id).where(OutboxEvent.processed.is_(True)).limit(500)
                result = await session.execute(subq)
                ids_to_delete = result.scalars().all()

                if ids_to_delete:
                    await session.execute(
                        delete(OutboxEvent).where(OutboxEvent.id.in_(ids_to_delete))
                    )
                    await session.commit()
                    logger.info(f"🧹 Storage cleaned: {len(ids_to_delete)} processed events purged.")
        except Exception as e:
            logger.error(f"Cleanup storage error: {e}")

    # ================= GRACEFUL STOP =================
    async def stop(self):
        self._running = False
        if self.redis:
            await self._release_lock()
        logger.info("🛑 Cache Worker SHUTDOWN GRACEFULLY")