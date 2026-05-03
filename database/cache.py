import asyncio
import time
import logging
import socket
import uuid
import orjson

from datetime import datetime, timezone, timedelta
from collections import OrderedDict
from typing import Any, Optional, Dict, List

import redis.asyncio as redis
from redis.exceptions import ResponseError

from config import config

logger = logging.getLogger("CacheManager")


class CacheManager:
    def __init__(self, url: str):
        self.namespace = "app"
        self.version = "v2"

        self.redis_url = url
        self.redis: Optional[redis.Redis] = None

        # 🔥 STRONGER NODE ID (collision-free)
        self.node_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"

        # ================= L1 CACHE (TRUE LRU) =================
        self._l1_cache: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()
        self._l1_max_size = 2000
        self._l1_lock = asyncio.Lock()

        # ================= SINGLEFLIGHT =================
        self._inflight: Dict[str, asyncio.Future] = {}
        self._inflight_lock = asyncio.Lock()

        # ================= STREAM =================
        self._stream_name = "cache:invalidate"
        self._group_name = "cache_group"
        self._consumer = self.node_id

        # ================= STATE =================
        self.is_alive = True
        self._tasks: List[asyncio.Task] = []

    # ================= START =================
    async def start(self):
        await self._connect()

        try:
            await self.redis.ping()

            try:
                await self.redis.xgroup_create(
                    self._stream_name,
                    self._group_name,
                    id="0",
                    mkstream=True
                )
            except ResponseError:
                pass

            self._tasks = [
                asyncio.create_task(self._stream_listener()),
                asyncio.create_task(self._pel_recovery()),
                asyncio.create_task(self._l1_cleanup())
            ]

            logger.info(f"🚀 Cache started [{self.node_id}]")

        except Exception as e:
            logger.critical(f"Cache startup failed: {e}")
            self.is_alive = False

    async def _connect(self):
        self.redis = redis.from_url(
            self.redis_url,
            max_connections=30,
            decode_responses=False
        )

    # ================= GET =================
    async def get(self, table: str, obj_id: Any) -> Optional[dict]:
        key = self._key(table, obj_id)
        now = datetime.now(timezone.utc)

        # ---------- L1 ----------
        async with self._l1_lock:
            if key in self._l1_cache:
                data, exp = self._l1_cache[key]
                if now < exp:
                    self._l1_cache.move_to_end(key)
                    return data
                else:
                    self._l1_cache.pop(key, None)

        # ---------- SINGLEFLIGHT ----------
        async with self._inflight_lock:
            if key in self._inflight:
                return await self._inflight[key]

            fut = asyncio.get_event_loop().create_future()
            self._inflight[key] = fut

        try:
            # ---------- L2 ----------
            raw = await asyncio.wait_for(self.redis.get(key), timeout=0.2)
            data = orjson.loads(raw) if raw else None

            if data:
                await self._set_l1(key, data, 60)

            fut.set_result(data)
            return data

        except Exception as e:
            fut.set_result(None)
            return None

        finally:
            async with self._inflight_lock:
                self._inflight.pop(key, None)

    # ================= SET =================
    async def set(self, table: str, obj_id: Any, data: dict, ttl: int = 3600):
        key = self._key(table, obj_id)

        try:
            if self.redis:
                await self.redis.setex(key, ttl, orjson.dumps(data))

            await self._set_l1(key, data, min(ttl, 60))

        except Exception as e:
            logger.error(f"SET error: {e}")

    # ================= DELETE =================
    async def delete(self, table: str, obj_id: Any):
        key = self._key(table, obj_id)

        async with self._l1_lock:
            self._l1_cache.pop(key, None)

        if self.redis:
            try:
                pipe = self.redis.pipeline()
                pipe.delete(key)

                payload = {"key": key, "sender": self.node_id}
                pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})

                await pipe.execute()

            except Exception as e:
                logger.error(f"DELETE error: {e}")

    # ================= L1 SET =================
    async def _set_l1(self, key: str, data: Any, ttl: int):
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)

        async with self._l1_lock:
            if key in self._l1_cache:
                self._l1_cache.move_to_end(key)

            self._l1_cache[key] = (data, exp)

            if len(self._l1_cache) > self._l1_max_size:
                self._l1_cache.popitem(last=False)

    # ================= STREAM LISTENER =================
    async def _stream_listener(self):
        while self.is_alive:
            try:
                res = await self.redis.xreadgroup(
                    groupname=self._group_name,
                    consumername=self._consumer,
                    streams={self._stream_name: ">"},
                    count=10,
                    block=2000
                )

                if not res:
                    continue

                for _, messages in res:
                    for msg_id, payload in messages:
                        await self._process(msg_id, payload)

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)

    async def _process(self, msg_id, payload):
        try:
            data = orjson.loads(payload[b"data"])

            if data["sender"] != self.node_id:
                async with self._l1_lock:
                    self._l1_cache.pop(data["key"], None)

            await self.redis.xack(self._stream_name, self._group_name, msg_id)

        except Exception as e:
            logger.error(f"Stream error: {e}")

    # ================= PEL RECOVERY =================
    async def _pel_recovery(self):
        while self.is_alive:
            try:
                await asyncio.sleep(30)

                result = await self.redis.xautoclaim(
                    name=self._stream_name,
                    groupname=self._group_name,
                    consumername=self._consumer,
                    min_idle_time=60000,
                    start_id="0-0",
                    count=10
                )

                if result and len(result) > 1:
                    for msg_id, payload in result[1]:
                        await self._process(msg_id, payload)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"PEL error: {e}")

    # ================= CLEANUP =================
    async def _l1_cleanup(self):
        while self.is_alive:
            try:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)

                async with self._l1_lock:
                    expired = [k for k, v in self._l1_cache.items() if now > v[1]]
                    for k in expired:
                        self._l1_cache.pop(k, None)

            except Exception as e:
                logger.error(f"L1 cleanup error: {e}")

    # ================= STOP =================
    async def stop(self):
        self.is_alive = False

        for t in self._tasks:
            if not t.done():
                t.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        if self.redis:
            await self.redis.close()

        logger.info("🛑 Cache stopped")

    # ================= UTILS =================
    def _key(self, table: str, obj_id: Any) -> str:
        return f"{self.namespace}:{table}:{obj_id}:{self.version}"


# INSTANCE
valkey = CacheManager(config.VALKEY_URL)