import asyncio
import time
import logging
import socket
import uuid
import orjson
import os
import hashlib

from datetime import datetime, timezone, timedelta
from collections import OrderedDict
from typing import Any, Optional, Dict, List

import redis.asyncio as redis
from redis.exceptions import ResponseError

from config import config

logger = logging.getLogger("CacheManager")




# ================= METRICS =================
class CacheMetrics:
    def __init__(self):
        self.l1_hits = 0
        self.l2_hits = 0
        self.misses = 0
        self.inflight_hits = 0
        self.errors = 0

        self.events_processed = 0

    def log(self):
        logger.info(
            f"📊 CACHE | L1:{self.l1_hits} L2:{self.l2_hits} MISS:{self.misses} "
            f"INF:{self.inflight_hits} ERR:{self.errors} EVT:{self.events_processed}"
        )


metrics = CacheMetrics()


# ================= SHARDING ENGINE (Redis Cluster READY) =================
class ShardRouter:
    def __init__(self, shards: int = 8):
        self.shards = shards

    def get_shard(self, key: str) -> int:
        h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        return h % self.shards


sharder = ShardRouter()


# ================= EVENT BUS (microcache invalidation) =================
class EventBus:
    def __init__(self):
        self.subscribers: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=1000)
        self.subscribers.append(q)
        return q

    async def publish(self, event: dict):
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


event_bus = EventBus()


# ================= CACHE MANAGER =================
class CacheManager:
    def __init__(self, url: str):
        self.namespace = "app"
        self.version = "v5"

        self.redis_url = url
        self.redis: Optional[redis.Redis] = None

        self.node_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

        # ================= L1 CACHE =================
        self._l1_cache: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()
        self._l1_max_size = min(8000, max(2000, (os.cpu_count() or 2) * 1200))
        self._l1_lock = asyncio.Lock()

        # ================= SINGLEFLIGHT =================
        self._inflight: Dict[str, asyncio.Future] = {}
        self._inflight_lock = asyncio.Lock()

        # ================= STREAMS =================
        self._stream_name = "cache:invalidate"
        self._group_name = "cache_group"
        self._consumer = self.node_id

        self._replication_stream = "cache:replicate"

        # ================= STATE =================
        self.is_alive = True
        self._tasks: List[asyncio.Task] = []

    # ================= CONNECT =================
    async def _connect(self):
        self.redis = redis.from_url(
            self.redis_url,
            max_connections=120,
            decode_responses=False,
            socket_keepalive=True,
            health_check_interval=30
        )

    # ================= START =================
    async def start(self):
        await self._connect()
        try:
            await self.redis.ping()
        
            # Stream va Guruhni majburiy yaratish (Silent Mode)
            await self._ensure_stream_setup()

            self._tasks = [
                asyncio.create_task(self._stream_listener()),
                asyncio.create_task(self._pel_recovery()),
                asyncio.create_task(self._l1_cleanup()),
                asyncio.create_task(self._metrics_logger()),
                asyncio.create_task(self._event_listener())
            ]
            logger.info(f"🚀 CACHE ONLINE [{self.node_id}]")
        except Exception as e:
            logger.critical(f"START FAIL: {e}")
            self.is_alive = False

    # ================= KEY =================
    def _key(self, table: str, obj_id: Any) -> str:
        shard = sharder.get_shard(f"{table}:{obj_id}")
        return f"{self.namespace}:{shard}:{table}:{obj_id}:{self.version}"
    

    # ================= CHANNELS CACHE =================
    async def get_channels(self):
        key = f"{self.namespace}:channels:active"
        raw = await self.redis.get(key)
        return orjson.loads(raw) if raw else None

    async def set_channels(self, channels_list: list):
        key = f"{self.namespace}:channels:active"
        await self.redis.setex(key, 3600, orjson.dumps(channels_list))

    async def invalidate_channels(self):
        """Kanal keshini majburiy tozalash"""
        key = f"{self.namespace}:channels:active"
        await self.redis.delete(key)
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
                    metrics.l1_hits += 1
                    return data

                self._l1_cache.pop(key, None)

        # ---------- SINGLEFLIGHT ----------
        async with self._inflight_lock:
            if key in self._inflight:
                metrics.inflight_hits += 1
                return await self._inflight[key]

            fut = asyncio.get_event_loop().create_future()
            self._inflight[key] = fut

        try:
            raw = await self.redis.get(key)
            data = orjson.loads(raw) if raw else None

            if data:
                metrics.l2_hits += 1
                await self._set_l1(key, data, 180)

            else:
                metrics.misses += 1

            if not fut.done():
                fut.set_result(data)

            return data

        except Exception as e:
            metrics.errors += 1

            if not fut.done():
                fut.set_result(None)

            logger.error(f"GET ERROR: {e}")
            return None

        finally:
            async with self._inflight_lock:
                self._inflight.pop(key, None)

    # ================= SET =================
    async def set(self, table: str, obj_id: Any, data: dict, ttl: int = 3600):
        key = self._key(table, obj_id)

        try:
            await self.redis.setex(key, ttl, orjson.dumps(data))
            await self._set_l1(key, data, min(ttl // 10, 180))

            # 🔥 event-driven sync
            await event_bus.publish({
                "type": "SET",
                "key": key,
                "node": self.node_id
            })

        except Exception as e:
            metrics.errors += 1
            logger.error(f"SET ERROR: {e}")

    # ================= DELETE =================
    async def delete(self, table: str, obj_id: Any):
        key = self._key(table, obj_id)

        async with self._l1_lock:
            self._l1_cache.pop(key, None)

        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.delete(key)

                payload = {
                    "key": key,
                    "sender": self.node_id
                }

                pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})
                pipe.xadd(self._replication_stream, {"data": orjson.dumps(payload)})

                await pipe.execute()

        except Exception as e:
            metrics.errors += 1
            logger.error(f"DELETE ERROR: {e}")

    # ================= L1 =================
    async def _set_l1(self, key: str, data: Any, ttl: int):
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)

        async with self._l1_lock:
            if key in self._l1_cache:
                self._l1_cache.move_to_end(key)

            self._l1_cache[key] = (data, exp)

            if len(self._l1_cache) > self._l1_max_size:
                self._l1_cache.popitem(last=False)

    # ================= STREAM LISTENER =================
    async def _ensure_stream_setup(self):
        """Stream va Guruh mavjudligini xatosiz ta'minlaydi"""
        try:
            # mkstream=True stream bo'lmasa uni ham yaratadi
            await self.redis.xgroup_create(
                self._stream_name, 
                self._group_name, 
                id="0", 
                mkstream=True
            )
            logger.info(f"✅ Redis Stream Group '{self._group_name}' tayyor.")
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass # Guruh allaqachon bor, muammo yo'q
            else:
                logger.warning(f"⚠️ Stream sozlashda kutilmagan holat: {e}")


    async def _stream_listener(self):
        while self.is_alive:
            try:
                res = await self.redis.xreadgroup(
                    self._group_name,
                    self._consumer,
                    {self._stream_name: ">"},
                    count=30,
                    block=2000 # Blok vaqtini biroz uzaytirdik (resurs tejash)
                )
                if not res:
                    continue

                for _, messages in res:
                    for msg_id, payload in messages:
                        await self._process(msg_id, payload)

            except ResponseError as e:
                if "NOGROUP" in str(e):
                    # AVTO-TUZATISH: Agar guruh o'chib ketgan bo'lsa, qayta yaratamiz
                    await self._ensure_stream_setup()
                    await asyncio.sleep(2)
                else:
                    logger.error(f"STREAM ERROR: {e}")
                    await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"STREAM UNKNOWN ERROR: {e}")
                await asyncio.sleep(5)




    async def _process(self, msg_id, payload):
        try:
            raw_data = payload.get(b"data")
            if not raw_data:
                # Agar ma'lumot bo'sh bo'lsa, xabarni ACK qilib navbatdan o'chiramiz
                await self.redis.xack(self._stream_name, self._group_name, msg_id)
                return

            data = orjson.loads(raw_data)

            if data.get("sender") != self.node_id and "key" in data:
                async with self._l1_lock:
                    self._l1_cache.pop(data["key"], None)

        except orjson.JSONDecodeError as je:
            logger.error(f"⚠️ JSON Parse Error in stream: {je}. Raw data: {raw_data}")
        except Exception as e:
            logger.error(f"❌ Process Stream Error: {e}")
        finally:
            # Xato bo'lsa ham xabarni ACK qilamiz, aks holda u DLQ ni to'ldirib tashlaydi va cheksiz aylanadi
            await self.redis.xack(self._stream_name, self._group_name, msg_id)

    # ================= 🔥 FIXED PEL RECOVERY =================
    async def _pel_recovery(self):
        while self.is_alive:
            await asyncio.sleep(30)

            try:
                claimed = await self.redis.xautoclaim(
                    self._stream_name,
                    self._group_name,
                    self._consumer,
                    60000,
                    "0-0",
                    20
                )

                if claimed and len(claimed) > 1:
                    for msg_id, payload in claimed[1]:
                        try:
                            raw_data = payload.get(b"data")
                            if raw_data:
                                data = orjson.loads(raw_data)
                                if "key" in data:
                                    async with self._l1_lock:
                                        self._l1_cache.pop(data["key"], None)

                            await self.redis.xack(
                                self._stream_name,
                                self._group_name,
                                msg_id
                            )
                            metrics.events_processed += 1

                        except orjson.JSONDecodeError:
                            # Buzilgan xabarni avtomatik o'chirish (DLQ ga tushmasligi uchun)
                            await self.redis.xack(self._stream_name, self._group_name, msg_id)
                        except Exception as inner:
                            logger.error(f"PEL ITEM ERROR: {inner}")

            except Exception as e:
                logger.error(f"PEL ERROR: {e}")

    # ================= EVENT BUS LISTENER =================
    async def _event_listener(self):
        q = event_bus.subscribe()

        while self.is_alive:
            event = await q.get()

            # Agar xabar aynan shu bot nusxasidan chiqqan bo'lsa, L1 keshni o'chirmaymiz!
            if event["type"] == "SET" and event.get("node") != self.node_id:
                async with self._l1_lock:
                    self._l1_cache.pop(event["key"], None)

    # ================= CLEANUP =================
    async def _l1_cleanup(self):
        while self.is_alive:
            await asyncio.sleep(60)

            now = datetime.now(timezone.utc)

            async with self._l1_lock:
                expired = [k for k, v in self._l1_cache.items() if now > v[1]]
                for k in expired:
                    self._l1_cache.pop(k, None)

    # ================= METRICS =================
    async def _metrics_logger(self):
        while self.is_alive:
            await asyncio.sleep(60)
            metrics.log()

    # ================= STOP =================
    async def stop(self):
        self.is_alive = False
    
    
    
        for t in self._tasks:
           t.cancel()
    
        await asyncio.gather(*self._tasks, return_exceptions=True)
    
        if self.redis:
            await self.redis.close()
    
        logger.info("✅ CACHE SHUTDOWN CLEAN (Group Preserved)")



# ================= 🔥 SMART INVALIDATE METHOD =================
    async def invalidate(self, table: str = None, obj_id: Any = None, key: str = None):
        """
        Workerlar tomonidan chaqiriladigan universal kesh tozalash metodi.
        Ham standart kalitlarni, ham maxsus kanallar keshini xavfsiz tozalaydi.
        """
        try:
            # 1. Agar maxsus kanallar jadvali so'ralgan bo'lsa
            if table == "channels" or key == f"{self.namespace}:channels:active":
                await self.invalidate_channels()
                logger.info("🧹 CacheManager: Channels active cache invalidated.")
                return

            # 2. Agar tayyor to'liq kalit (key) berilgan bo'lsa
            if key:
                async with self._l1_lock:
                    self._l1_cache.pop(key, None)
                if self.redis:
                    await self.redis.delete(key)
                return

            # 3. Agar standart table va obj_id berilgan bo'lsa
            if table and obj_id:
                target_key = self._key(table, obj_id)
                async with self._l1_lock:
                    self._l1_cache.pop(target_key, None)
                if self.redis:
                    await self.redis.delete(target_key)
                logger.info(f"🧹 CacheManager: Invalidated key {target_key}")

        except Exception as e:
            metrics.errors += 1
            logger.error(f"❌ INVALIDATE ERROR: {e}")




cache_manager = CacheManager(config.VALKEY_URL)


valkey = cache_manager