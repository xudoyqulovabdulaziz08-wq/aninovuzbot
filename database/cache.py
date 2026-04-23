import json
import logging
import time
from datetime import datetime
from typing import Any, Optional, Dict, List
from sqlalchemy import inspect
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError
from config import config
logger = logging.getLogger("CacheManager")


class CacheManager:
    def __init__(self, url: str):
        self.redis = redis.from_url(
            url, 
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
            max_connections=30
        )
        self.version = "v1"
        self.namespace = "cache"
        
        # 0.15 BALL UPGRADE: Monitoring metrics
        self.stats = {"hits": 0, "misses": 0, "errors": 0}
        
    def _get_key(self, table_name: str, obj_id: Any) -> str:
        return f"{self.namespace}:{table_name}:{obj_id}:{self.version}"

    def _default_serializer(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode('utf-8', errors='ignore')
        return str(obj)
    
    # ================= MONITORING (PREMIUM FEATURE) =================

    def get_hit_ratio(self) -> dict:
        """Kesh samaradorligini hisoblash uchun statistika."""
        total = self.stats["hits"] + self.stats["misses"]
        ratio = (self.stats["hits"] / total * 100) if total > 0 else 0
        return {
            "hit_ratio": f"{ratio:.2f}%",
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "errors": self.stats["errors"]
        }

    # ================= READ OPERATIONS =================

    async def get(self, table_name: str, obj_id: Any) -> Optional[dict]:
        try:
            key = self._get_key(table_name, obj_id)
            data = await self.redis.get(key)
            
            if data is None: # Strict check for "0" or "false" cases
                self.stats["misses"] += 1
                return None
            
            self.stats["hits"] += 1
            return json.loads(data)
        except (json.JSONDecodeError, TypeError) as je:
            logger.error(f"Corrupted JSON for {obj_id}: {je}")
            self.stats["errors"] += 1
            return None
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
            self.stats["errors"] += 1
            return None

    async def get_many(self, table_name: str, obj_ids: List[Any]) -> Dict[Any, Optional[dict]]:
        if not obj_ids: return {}
        
        keys = [self._get_key(table_name, oid) for oid in obj_ids]
        try:
            raw_data = await self.redis.mget(keys)
            results = {}
            
            for oid, data in zip(obj_ids, raw_data):
                if data is None:
                    self.stats["misses"] += 1
                    results[oid] = None
                    continue
                
                try:
                    self.stats["hits"] += 1
                    results[oid] = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    self.stats["errors"] += 1
                    results[oid] = None
            return results
        except Exception as e:
            logger.error(f"MGET failure: {e}")
            self.stats["errors"] += 1
            return {oid: None for oid in obj_ids}

    # ================= WRITE OPERATIONS =================
    
    async def set_many(self, table_name: str, mapping: Dict[Any, Any], expire: int = 3600):
        """
        10/10 UPGRADE: 
        - Pipeline with partial success check
        - Error tracking per batch
        """
        if not mapping: return
        
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for obj_id, value in mapping.items():
                    key = self._get_key(table_name, obj_id)
                    serialized = json.dumps(value, default=self._default_serializer, ensure_ascii=False)
                    pipe.set(key, serialized, ex=expire)
                
                # Natijalarni tekshirish (Optional but pro-level)
                responses = await pipe.execute(raise_on_error=False)
                
                failed_count = sum(1 for r in responses if isinstance(r, Exception))
                if failed_count > 0:
                    logger.error(f"Pipeline partial failure: {failed_count} items failed.")
                    self.stats["errors"] += failed_count
                    
        except Exception as e:
            logger.error(f"Pipeline total failure: {e}")
            self.stats["errors"] += 1

    async def set_model(self, obj: Any, expire: int = 3600, exclude_fields: Optional[set] = None):
        if obj is None: return
        try:
            state = inspect(obj, raiseerr=False)
            if state is None or state.detached: return
            
            mapper = state.mapper
            pk_val = ":".join(str(getattr(obj, col.key)) for col in mapper.primary_key)
            data = {c.key: getattr(obj, c.key) for c in mapper.column_attrs if c.key not in (exclude_fields or set())}
            
            key = self._get_key(obj.__tablename__, pk_val)
            await self.redis.set(key, json.dumps(data, default=self._default_serializer, ensure_ascii=False), ex=expire)
        except Exception as e:
            logger.error(f"Model cache failure: {e}")
            self.stats["errors"] += 1

    async def close(self):
        await self.redis.close()

valkey = CacheManager(url=config.VALKEY_URL)