import json
import logging
from datetime import datetime
from typing import Any, Optional, Dict
from sqlalchemy import inspect
from config import config
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError

# 1. STRUCTURED LOGGING
logger = logging.getLogger("CacheManager")

class CacheManager:
    def __init__(self, url: str):
        self.redis = redis.from_url(
            url, 
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
            max_connections=20
        )
        self.version = "v1"
        # 2. CACHE NAMESPACE SEPARATION (Advanced Level)
        self.namespace = "cache"

    def _get_key(self, table_name: str, obj_id: Any) -> str:
        """Global naming convention: cache:table:id:v1"""
        return f"{self.namespace}:{table_name}:{obj_id}:{self.version}"

    def _default_serializer(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode('utf-8', errors='ignore')
        return str(obj)

    async def get(self, table_name: str, obj_id: Any) -> Optional[dict]:
        try:
            key = self._get_key(table_name, obj_id)
            data = await self.redis.get(key)
            if not data:
                return None
            
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError) as je:
                logger.error(f"Corrupted cache data for {key}: {je}")
                return None

        except (RedisError, ConnectionError, TimeoutError) as re:
            logger.warning(f"Valkey link unstable (Read): {re}")
            return None
        except Exception as e:
            logger.error(f"Unexpected cache read failure: {e}")
            return None

    async def set_model(self, obj: Any, expire: int = 3600, exclude_fields: Optional[set] = None):
        """
        SQLAlchemy modelini keshga saqlash.
        1. PERFORMANCE: Selective fields optimization (Micro-optimization)
        2. NAMESPACE: Proper key separation.
        """
        if obj is None:
            return

        try:
            state = inspect(obj, raise_err=False)
            if state is None or (hasattr(state, 'detached') and state.detached):
                return

            mapper = state.mapper
            pk_values = [getattr(obj, col.key) for col in mapper.primary_key]
            pk_val = ":".join(str(v) for v in pk_values)
            
            # 1. MICRO-OPTIMIZATION: Selective Fields
            # Agar modelda juda katta "description" yoki "long_text" bo'lsa, ularni keshlash shart emas
            exclude = exclude_fields or set()
            data = {
                c.key: getattr(obj, c.key) 
                for c in mapper.column_attrs 
                if c.key not in exclude
            }

            key = self._get_key(obj.__tablename__, pk_val)
            
            serialized_data = json.dumps(
                data, 
                default=self._default_serializer, 
                ensure_ascii=False
            )
            
            await self.redis.set(key, serialized_data, ex=expire)

        except (RedisError, ConnectionError, TimeoutError) as re:
            logger.warning(f"Valkey link unstable (Write): {re}")
        except Exception as e:
            logger.error(f"Global cache system failure: {e}")

    async def delete(self, table_name: str, obj_id: Any):
        try:
            key = self._get_key(table_name, obj_id)
            await self.redis.delete(key)
        except RedisError as re:
            logger.warning(f"Valkey delete failed: {re}")

    async def close(self):
        await self.redis.close()
        logger.info("Valkey connection pool closed.")

# ✅ Singleton instance
valkey = CacheManager(config.VALKEY_URL)