import json
from datetime import datetime
import redis.asyncio as redis
from sqlalchemy import inspect
from config import config


class CacheManager:
    def __init__(self, url: str):
        self.redis = redis.from_url(url, decode_responses=True)

    def _get_key(self, table_name: str, obj_id):
        return f"{table_name}:{obj_id}"

    async def get(self, table_name: str, obj_id):
        """Keshdan ma'lumotni olish"""
        key = self._get_key(table_name, obj_id)
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def set(self, obj, expire: int = 3600):
        """Obyektni keshga saqlash (Default: 1 soat)"""
        mapper = inspect(obj).mapper
        data = {
            c.key: getattr(obj, c.key)
            for c in mapper.column_attrs
            if not isinstance(getattr(obj, c.key), (bytes, datetime))
        }
        pk_name = mapper.primary_key[0].name
        pk_value = getattr(obj, pk_name)
        key = self._get_key(obj.__tablename__, pk_value)
        await self.redis.set(key, json.dumps(data, default=str), ex=expire)

    async def invalidate(self, table_name: str, obj_id):
        """Keshni o'chirish"""
        key = self._get_key(table_name, obj_id)
        await self.redis.delete(key)


# ✅ URL .env faylidan olinadi (credentials GitHub'da ko'rinmaydi)
VALKEY_URL = config.VALKEY_URL
valkey = CacheManager(VALKEY_URL)