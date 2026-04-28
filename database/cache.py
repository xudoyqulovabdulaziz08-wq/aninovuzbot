#database/cache.py
import logging
import orjson
import asyncio
import time
import socket
from datetime import datetime, timezone, timedelta
from collections import OrderedDict
from typing import Any, Optional, Dict, List
import redis.asyncio as redis
# Asosiy xatolikni mana bu yerda to'g'irlaymiz:
from redis.exceptions import ResponseError, RedisError 
from config import config

logger = logging.getLogger("CacheManager")
class CacheManager:
    def __init__(self, url: str):
        self.namespace = "app"   # qo'shish kerak
        self.version = "v1" 
        self.redis_url = url
        self.redis: Optional[redis.Redis] = None
        self.node_id = f"{socket.gethostname()}_{int(time.time())}"
        
        # 1. Real LRU L1 Cache
        self._l1_cache: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()
        self._l1_max_size = 2000
        self._l1_lock = asyncio.Lock()
        
        # 2. Race-Free Singleflight
        self._inflight: Dict[str, asyncio.Future] = {}
        self._inflight_lock = asyncio.Lock()

        # 3. Stream Infrastructure (Reliable PEL)
        self._stream_name = "cache:invalidation:stream"
        self._group_name = "cache_invalidation_group"
        self._consumer_name = self.node_id

        # 4. Metrics & Lifecycle
        self.is_alive = True
        self._tasks: List[asyncio.Task] = []

        

    async def start(self):
        """Startup with PEL recovery and auto-claim."""
        await self._connect()
        try:
            await self.redis.ping()
            try:
                await self.redis.xgroup_create(self._stream_name, self._group_name, id="0", mkstream=True)
            except ResponseError: pass

            # Background Tasks
            self._tasks.append(asyncio.create_task(self._reliable_stream_listener()))
            self._tasks.append(asyncio.create_task(self._pel_recovery_loop())) # PEL Recovery
            self._tasks.append(asyncio.create_task(self._l1_cleanup_loop()))
            logger.info(f"🏆 100% FINAL BOSS: Cache active on {self.node_id}")
        except Exception as e:
            logger.critical(f"Startup failure: {e}")
            self.is_alive = False

    async def _connect(self):
        self.redis = redis.from_url(self.redis_url, max_connections=100)

    # ================= 1. PEL RECOVERY (XAUTOCLAIM) =================

    async def _pel_recovery_loop(self):
        """Boshqa node'larda 'osilib' qolgan xabarlarni qayta ishlash."""
        while True:
            try:
                await asyncio.sleep(30) # Har 30 soniyada stuck xabarlarni tekshirish
                if not self.is_alive: continue

                # 60 soniyadan ko'p ushlanib qolgan xabarlarni o'zimizga olish
                result = await self.redis.xautoclaim(
                    name=self._stream_name,
                    groupname=self._group_name,
                    consumername=self._consumer_name,
                    min_idle_time=60000, 
                    start_id="0-0",
                    count=10
                )
                
                # result[1] — bu claim qilingan xabarlar
                for msg_id, payload in result[1]:
                    await self._process_stream_msg(msg_id, payload)
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"PEL Recovery error: {e}")

    async def _process_stream_msg(self, msg_id, payload):
        try:
            data = orjson.loads(payload[b"data"])
            if data["sender"] != self.node_id:
                async with self._l1_lock:
                    self._l1_cache.pop(data["key"], None)
            await self.redis.xack(self._stream_name, self._group_name, msg_id)
        except Exception as e:
            logger.error(f"Message processing failed: {e}")

    async def _reliable_stream_listener(self):
        while True:
            try:
                # Faqat yangi xabarlarni o'qish
                response = await self.redis.xreadgroup(
                    groupname=self._group_name, consumername=self._consumer_name,
                    streams={self._stream_name: ">"}, count=10, block=2000
                )
                if response:
                    for _, messages in response:
                        for msg_id, payload in messages:
                            await self._process_stream_msg(msg_id, payload)
            except asyncio.CancelledError: break
            except Exception as e:
                await asyncio.sleep(2)

    # ================= 2. ADVANCED METRICS (ISOLATION) =================

    async def _track(self, metric: str, latency: float = 0):
        """Node-based isolated metrics + Latency distribution."""
        try:
            pipe = self.redis.pipeline()
            # 1. Per-node breakdown
            pipe.hincrby(f"metrics:node:{self.node_id}", metric, 1)
            # 2. Global aggregate
            pipe.hincrby("metrics:global", metric, 1)
            # 3. Latency tracking (P95/P99 uchun)
            if latency > 0:
                # Latencyni 1ms aniqlikda Sorted Set'ga yozish
                ts = int(time.time() // 60) # Har minut uchun alohida set
                pipe.zadd(f"metrics:latency:{ts}", {str(time.time()): latency})
                pipe.expire(f"metrics:latency:{ts}", 3600) # 1 soat saqlash
            await pipe.execute()
        except: pass

    # ================= 3. GET (RACE-FREE SINGLEFLIGHT) =================

    async def get(self, table_name: str, obj_id: Any) -> Optional[dict]:
        start_ts = time.perf_counter()
        key = self._get_key(table_name, obj_id)
        
        async with self._l1_lock:
            if key in self._l1_cache:
                val, exp = self._l1_cache[key]
                if datetime.now(timezone.utc) < exp:
                    self._l1_cache.move_to_end(key)
                    await self._track("l1_hit")
                    return val
                del self._l1_cache[key]

        async with self._inflight_lock:
            if key in self._inflight:
                # Waiterlar uchun data isolation
                try:
                    return await self._inflight[key]
                except: return None
            
            future = asyncio.get_event_loop().create_future()
            self._inflight[key] = future

        try:
            raw = await asyncio.wait_for(self.redis.get(key), timeout=0.5)
            data = orjson.loads(raw) if raw else None
            
            if data:
                await self._track("l2_hit", time.perf_counter() - start_ts)
                await self._set_l1(key, data, ttl=60)
            else:
                await self._track("miss")
            
            if not future.done(): future.set_result(data)
            return data
        except Exception as e:
            if not future.done(): future.set_exception(e)
            await self._track("error")
            return None
        finally:
            # Future cleanup faqat owner tomonidan
            async with self._inflight_lock:
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)

    def _get_key(self, table_name: str, obj_id: Any) -> str:
        return f"{self.namespace}:{table_name}:{obj_id}:{self.version}"

    async def _set_l1(self, key: str, data: Any, ttl: int):
        async with self._l1_lock:
            if len(self._l1_cache) >= self._l1_max_size:
                self._l1_cache.popitem(last=False)
            self._l1_cache[key] = (data, datetime.now(timezone.utc) + timedelta(seconds=ttl))
            self._l1_cache.move_to_end(key)

    async def _l1_cleanup_loop(self):
        while self.is_alive:
            try:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)
                async with self._l1_lock:
                    expired = [k for k, v in self._l1_cache.items() if now > v[1]]
                    for k in expired:
                        del self._l1_cache[k]
            except Exception as e:
                logger.error(f"L1 Cleanup error: {e}")

valkey = CacheManager(url=config.VALKEY_URL)