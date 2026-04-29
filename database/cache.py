import logging
import orjson
import asyncio
import time
import socket
from datetime import datetime, timezone, timedelta
from collections import OrderedDict
from typing import Any, Optional, Dict, List
import redis.asyncio as redis
from redis.exceptions import ResponseError, RedisError 
from config import config

logger = logging.getLogger("CacheManager")

class CacheManager:
    def __init__(self, url: str):
        self.namespace = "app"
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
            self._tasks.append(asyncio.create_task(self._pel_recovery_loop())) 
            self._tasks.append(asyncio.create_task(self._l1_cleanup_loop()))
            logger.info(f"🏆 100% FINAL BOSS: Cache active on {self.node_id}")
        except Exception as e:
            logger.critical(f"Startup failure: {e}")
            self.is_alive = False

    async def _connect(self):
        # max_connections'ni Render Free uchun 20 ga tushirdik
        self.redis = redis.from_url(self.redis_url, max_connections=20, decode_responses=False)

    async def _pel_recovery_loop(self):
        while self.is_alive: # is_alive qo'shildi
            try:
                await asyncio.sleep(30)
                if not self.is_alive: break

                result = await self.redis.xautoclaim(
                    name=self._stream_name,
                    groupname=self._group_name,
                    consumername=self._consumer_name,
                    min_idle_time=60000, 
                    start_id="0-0",
                    count=10
                )
                
                if result and len(result) > 1:
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
        while self.is_alive: # is_alive qo'shildi
            try:
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
                if self.is_alive:
                    await asyncio.sleep(2)

    async def _track(self, metric: str, latency: float = 0):
        try:
            pipe = self.redis.pipeline()
            pipe.hincrby(f"metrics:node:{self.node_id}", metric, 1)
            pipe.hincrby("metrics:global", metric, 1)
            if latency > 0:
                ts = int(time.time() // 60)
                pipe.zadd(f"metrics:latency:{ts}", {str(time.time()): latency})
                pipe.expire(f"metrics:latency:{ts}", 3600)
            await pipe.execute()
        except: pass

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
            async with self._inflight_lock:
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)

    def _get_key(self, table_name: str, obj_id: Any) -> str:
        return f"{self.namespace}:{table_name}:{obj_id}:{self.version}"
    # CacheManager sinfi ichiga qo'shing:

    async def delete(self, table_name: str, obj_id: Any):
        key = self._get_key(table_name, obj_id)
        async with self._l1_lock:
            self._l1_cache.pop(key, None)
        if self.redis:
            try:
                pipe = self.redis.pipeline()
                pipe.delete(key)
                # Stream orqali boshqa instansiyalarga invalidatsiya yuborish
                payload = {"key": key, "sender": self.node_id}
                pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})
                await pipe.execute()
            except Exception as e:
                logger.error(f"Cache delete error: {e}")

    async def set(self, table_name: str, obj_id: Any, data: Any, ttl: int = 3600):
        key = self._get_key(table_name, obj_id)
        if self.redis:
            try:
                await self.redis.setex(key, ttl, orjson.dumps(data))
                await self._set_l1(key, data, ttl=min(ttl, 60))
            except Exception as e:
                logger.error(f"Cache set error: {e}")
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
                if self.is_alive:
                    logger.error(f"L1 Cleanup error: {e}")

    async def stop(self):
        """Cleanup tasks and close redis connection."""
        self.is_alive = False
        logger.info("🛑 Shutting down CacheManager...")
        
        # Fondagi vazifalarni to'xtatish
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Redis ulanishini yopish
        if self.redis:
            await self.redis.close()
            logger.info("✅ Valkey (Redis) connection closed safely.")

valkey = CacheManager(url=config.VALKEY_URL)