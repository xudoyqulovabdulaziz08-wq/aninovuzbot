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


# ================= CACHE MANAGER (PRODUCTION READY) =================
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

        # ================= STREAMS (CLUSTER SYNC) =================
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
            
            # Stream va Guruhni xavfsiz sozlash
            await self._ensure_stream_setup()

            # Fondagi barcha vazifalarni ishga tushirish
            self._tasks = [
                asyncio.create_task(self._stream_listener()),
                asyncio.create_task(self._pel_recovery()),
                asyncio.create_task(self._l1_cleanup()),
                asyncio.create_task(self._metrics_logger())
            ]
            logger.info(f"🚀 CACHE ONLINE CONTROL KEY [{self.node_id}] | L1 Max Size: {self._l1_max_size}")
        except Exception as e:
            logger.critical(f"🚨 START FAIL: {e}")
            self.is_alive = False

    # ================= KEY ENGINE =================
    def _key(self, table: str, obj_id: Any) -> str:
        shard = sharder.get_shard(f"{table}:{obj_id}")
        return f"{self.namespace}:{shard}:{table}:{obj_id}:{self.version}"

    # ================= ANIME SEARCH & DETAILS CACHE =================
    async def set_anime_search_map(self, search_data: dict):
        """
        🚀 Barcha anime nomlari va IDlarini qidiruv uchun saqlash (30 daqiqa)
        """
        key = f"{self.namespace}:anime_search:all_titles"
        try:
            raw_data = orjson.dumps(search_data)
            if self.redis:
                # L2 distributed keshga yozamiz va tarmoqqa xabar chiqaramiz
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.setex(key, 1800, raw_data)
                    payload = {"key": key, "sender": self.node_id, "action": "SET"}
                    pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})
                    await pipe.execute()

            # L1 keshga nusxasini yuklaymiz
            await self._set_l1(key, search_data, 1800)
            logger.info(f"🔥 CacheManager: {len(search_data)} ta anime qidiruv keshiga yozildi va tarmoqqa tarqatildi.")
        except Exception as e:
            metrics.errors += 1
            logger.error(f"❌ SET ANIME SEARCH MAP ERROR: {e}")

    async def get_anime_search_map(self) -> Optional[dict]:
        """
        🔎 Qidiruv xaritasini L1 yoki L2 keshdan tezkor olish (0-1ms)
        """
        key = f"{self.namespace}:anime_search:all_titles"
        
        # 1. L1 Local Memory Cache
        async with self._l1_lock:
            if key in self._l1_cache:
                data, exp = self._l1_cache[key]
                if datetime.now(timezone.utc) < exp:
                    self._l1_cache.move_to_end(key)
                    metrics.l1_hits += 1
                    return data.copy() if hasattr(data, "copy") else data
                self._l1_cache.pop(key, None)

        # 2. Singleflight Lock orqali L2 (Redis/Valkey)
        async with self._inflight_lock:
            if key in self._inflight:
                metrics.inflight_hits += 1
                return await self._inflight[key]
            fut = asyncio.get_event_loop().create_future()
            self._inflight[key] = fut

        try:
            raw = await self.redis.get(key) if self.redis else None
            data = orjson.loads(raw) if raw else None
            if data:
                metrics.l2_hits += 1
                await self._set_l1(key, data, 1800)
            else:
                metrics.misses += 1
            
            if not fut.done():
                fut.set_result(data)
            return data.copy() if (data and hasattr(data, "copy")) else data
        except Exception as e:
            metrics.errors += 1
            if not fut.done():
                fut.set_result(None)
            logger.error(f"❌ GET ANIME SEARCH MAP ERROR: {e}")
            return None
        finally:
            async with self._inflight_lock:
                self._inflight.pop(key, None)

    async def update_single_anime_in_search_map(self, anime_id: int, title: str, year: int):
        """
        🔄 Qidiruv xaritasini buzmasdan ichiga yangi element qo'shish va tarmoqqa sinxronlash
        """
        key = f"{self.namespace}:anime_search:all_titles"
        try:
            current_map = await self.get_anime_search_map() or {}
            current_map[str(anime_id)] = f"{title} ({year})"
            
            raw_data = orjson.dumps(current_map)
            if self.redis:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.setex(key, 1800, raw_data)
                    payload = {"key": key, "sender": self.node_id, "action": "SET"}
                    pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})
                    await pipe.execute()

            await self._set_l1(key, current_map, 1800)
            logger.info(f"🔄 CacheManager: Yangi anime [{anime_id}] qidiruv xaritasiga qo'shildi cluster tarqatildi.")
        except Exception as e:
            metrics.errors += 1
            logger.error(f"❌ UPDATE SINGLE ANIME IN SEARCH MAP ERROR: {e}")

    async def set_episode_file_id(self, anime_id: int, episode: int, file_id: str, ttl: int = 86400):
        """
        🎬 Epizod video faylini L1 va L2 keshga yozish
        """
        table = "anime_episodes"
        obj_id = f"{anime_id}_{episode}"
        key = self._key(table, obj_id)
        data = {"file_id": file_id}
        try:
            if self.redis:
                await self.redis.setex(key, ttl, orjson.dumps(data))
            await self._set_l1(key, data, min(ttl // 10, 900))
        except Exception as e:
            metrics.errors += 1
            logger.error(f"❌ SET EPISODE FILE ID ERROR: {e}")

    async def get_episode_file_id(self, anime_id: int, episode: int) -> Optional[str]:
        table = "anime_episodes"
        obj_id = f"{anime_id}_{episode}"
        res = await self.get(table, obj_id)
        return res.get("file_id") if res else None
    
    # ================= CHANNELS CACHE =================
    async def get_channels(self) -> Optional[list]:
        key = f"{self.namespace}:channels:active"
        try:
            # Avval L1 local xotirani tekshirish
            async with self._l1_lock:
                if key in self._l1_cache:
                    data, exp = self._l1_cache[key]
                    if datetime.now(timezone.utc) < exp:
                        return data
            
            raw = await self.redis.get(key) if self.redis else None
            if raw:
                res = orjson.loads(raw)
                await self._set_l1(key, res, 600)
                return res
            return None
        except Exception as e:
            logger.error(f"❌ GET CHANNELS ERROR: {e}")
            return None

    async def set_channels(self, channels_list: list):
        key = f"{self.namespace}:channels:active"
        try:
            raw_data = orjson.dumps(channels_list)
            if self.redis:
                await self.redis.setex(key, 3600, raw_data)
            await self._set_l1(key, channels_list, 600)
        except Exception as e:
            logger.error(f"❌ SET CHANNELS ERROR: {e}")

    # ================= CORE GET / SET =================
    async def get(self, table: str, obj_id: Any) -> Optional[dict]:
        key = self._key(table, obj_id)
        now = datetime.now(timezone.utc)

        # ---------- L1 LOCAL CACHE ----------
        async with self._l1_lock:
            if key in self._l1_cache:
                data, exp = self._l1_cache[key]
                if now < exp:
                    self._l1_cache.move_to_end(key)
                    metrics.l1_hits += 1
                    return data.copy() if hasattr(data, "copy") else data
                self._l1_cache.pop(key, None)

        # ---------- SINGLEFLIGHT PATTERN ----------
        async with self._inflight_lock:
            if key in self._inflight:
                metrics.inflight_hits += 1
                return await self._inflight[key]
            fut = asyncio.get_event_loop().create_future()
            self._inflight[key] = fut

        try:
            raw = await self.redis.get(key) if self.redis else None
            data = orjson.loads(raw) if raw else None

            if data:
                metrics.l2_hits += 1
                await self._set_l1(key, data, 180)
            else:
                metrics.misses += 1

            if not fut.done():
                fut.set_result(data)
            return data.copy() if (data and hasattr(data, "copy")) else data
        except Exception as e:
            metrics.errors += 1
            if not fut.done():
                fut.set_result(None)
            logger.error(f"❌ CORE GET ERROR: {e}")
            return None
        finally:
            async with self._inflight_lock:
                self._inflight.pop(key, None)

    async def set(self, table: str, obj_id: Any, data: dict, ttl: int = 3600):
        key = self._key(table, obj_id)
        try:
            raw = orjson.dumps(data)
            if self.redis:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.setex(key, ttl, raw)
                    payload = {"key": key, "sender": self.node_id, "action": "SET"}
                    pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})
                    await pipe.execute()

            await self._set_l1(key, data, min(ttl // 10, 180))
        except Exception as e:
            metrics.errors += 1
            logger.error(f"❌ CORE SET ERROR: {e}")

    # ================= 🔥 SMART UNIVERSAL INVALIDATE =================
    async def invalidate(self, table: str = None, obj_id: Any = None, key: str = None, broadcast: bool = True):
        """
        🧹 Worker va repozitoriy tomonidan chaqiriladigan universal tozalash metodi.
        Klaster tarmog'idagi barcha node-larning mahalliy L1 keshini bir vaqtda tozalaydi.
        """
        try:
            # Maxsus yo'naltirish (Search Map uchun fallback)
            if (table == "anime_list" and obj_id == "search_map") or (key and "anime_search" in key):
                key = f"{self.namespace}:anime_search:all_titles"
                table = None
                obj_id = None

            keys_to_delete = []

            # Channels event aniqlash
            is_channel_event = (
                table == "channels" or 
                (key and ("channels" in key or key == f"{self.namespace}:channels:active"))
            )

            if is_channel_event:
                if table == "channels" and obj_id and obj_id not in ["all_list", "active_list"]:
                    keys_to_delete.append(self._key(table, obj_id))
                
                keys_to_delete.append(self._key("channels", "all_list"))
                keys_to_delete.append(self._key("channels", "active_list"))
                keys_to_delete.append(f"{self.namespace}:channels:active")
            elif key:
                keys_to_delete.append(key)
            elif table and obj_id:
                keys_to_delete.append(self._key(table, obj_id))

            if not keys_to_delete:
                return

            # Mahalliy L1 keshdan o'chirish
            async with self._l1_lock:
                for k in keys_to_delete:
                    self._l1_cache.pop(k, None)

            # Redis (L2) dan o'chirish va Pipeline orqali tarmoqqa tarqatish
            if self.redis:
                async with self.redis.pipeline(transaction=True) as pipe:
                    for k in keys_to_delete:
                        pipe.delete(k)
                        if broadcast:
                            payload = {"key": k, "sender": self.node_id, "action": "DEL"}
                            pipe.xadd(self._stream_name, {"data": orjson.dumps(payload)})
                            pipe.xadd(self._replication_stream, {"data": orjson.dumps(payload)})
                    await pipe.execute()

            logger.info(f"🧹 CacheManager Invalidation Cleaned keys: {keys_to_delete} (Broadcast={broadcast})")
        except Exception as e:
            metrics.errors += 1
            logger.error(f"❌ INVALIDATE METODIDA XATOLIK: {e}")

    # ================= INTERNAL L1 SET =================
    async def _set_l1(self, key: str, data: Any, ttl: int):
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        async with self._l1_lock:
            if key in self._l1_cache:
                self._l1_cache.move_to_end(key)
            self._l1_cache[key] = (data, exp)
            if len(self._l1_cache) > self._l1_max_size:
                self._l1_cache.popitem(last=False)

    # ================= REDIS STREAMS BROKER CONTROL =================
    async def _ensure_stream_setup(self):
        try:
            await self.redis.xgroup_create(
                self._stream_name, self._group_name, id="0", mkstream=True
            )
            logger.info(f"✅ Redis Stream Group '{self._group_name}' tayyorlandi.")
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass
            else:
                logger.warning(f"⚠️ Stream sozlashda kutilmagan holat: {e}")

    async def _stream_listener(self):
        while self.is_alive:
            try:
                res = await self.redis.xreadgroup(
                    self._group_name, self._consumer, {self._stream_name: ">"}, count=50, block=2000
                )
                if not res:
                    continue

                for _, messages in res:
                    for msg_id, payload in messages:
                        try:
                            raw_data = payload.get(b"data")
                            if raw_data:
                                data = orjson.loads(raw_data)
                                # 🔥 ASOSIY KLASTER SINXRONIZATSIYASI:
                                # Agar xabar boshqa server/node dan chiqqan bo'lsa, mahalliy L1 keshni urib tushiramiz!
                                if data.get("sender") != self.node_id and "key" in data:
                                    async with self._l1_lock:
                                        self._l1_cache.pop(data["key"], None)
                                    metrics.events_processed += 1
                        except Exception as inner:
                            logger.error(f"❌ Msg Process Error: {inner}")
                        finally:
                            await self.redis.xack(self._stream_name, self._group_name, msg_id)
            except ResponseError as e:
                if "NOGROUP" in str(e):
                    await self._ensure_stream_setup()
                    await asyncio.sleep(2)
                else:
                    logger.error(f"❌ Stream Listener Response Error: {e}")
                    await asyncio.sleep(5)
            except Exception as e:
                if self.is_alive:
                    logger.error(f"❌ Stream Unknown Error: {e}")
                    await asyncio.sleep(5)

    async def _pel_recovery(self):
        """Avariya holatida ACK qilinmay qolib ketgan xabarlarni qayta tiklash (PEL)"""
        while self.is_alive:
            await asyncio.sleep(60)
            try:
                claimed = await self.redis.xautoclaim(
                    self._stream_name, self._group_name, self._consumer, 60000, "0-0", count=30
                )
                if claimed and len(claimed) > 1 and claimed[1]:
                    for msg_id, payload in claimed[1]:
                        try:
                            raw_data = payload.get(b"data")
                            if raw_data:
                                data = orjson.loads(raw_data)
                                if data.get("sender") != self.node_id and "key" in data:
                                    async with self._l1_lock:
                                        self._l1_cache.pop(data["key"], None)
                        except Exception:
                            pass
                        finally:
                            await self.redis.xack(self._stream_name, self._group_name, msg_id)
            except Exception as e:
                if self.is_alive:
                    logger.debug(f"PEL Recovery Loop Info: {e}")

    async def _l1_cleanup(self):
        """L1 kesh ichidagi muddati o'tgan kalitlarni tozalab xotirani bo'shatish"""
        while self.is_alive:
            await asyncio.sleep(30)
            try:
                now = datetime.now(timezone.utc)
                async with self._l1_lock:
                    expired = [k for k, v in self._l1_cache.items() if now > v[1]]
                    for k in expired:
                        self._l1_cache.pop(k, None)
            except Exception as e:
                logger.error(f"❌ L1 Cleanup Error: {e}")

    async def _metrics_logger(self):
        while self.is_alive:
            await asyncio.sleep(60)
            if self.is_alive:
                metrics.log()

    # ================= CLEAN STOP =================
    async def stop(self):
        self.is_alive = False
        for t in self._tasks:
            if not t.done():
                t.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        if self.redis:
            await self.redis.close()
        logger.info("✅ CACHE SHUTDOWN CLEAN (Cluster Streams Preserved)")


cache_manager = CacheManager(config.VALKEY_URL)
valkey = cache_manager