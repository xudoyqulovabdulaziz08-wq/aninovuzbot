import json
from datetime import datetime
import redis.asyncio as redis
from sqlalchemy import inspect

class CacheManager:
    def __init__(self, url: str):
        # Aiven Valkey uchun SSL ulanish
        self.redis = redis.from_url(url, decode_responses=True)

    def _get_key(self, table_name: str, obj_id: any):
        return f"{table_name}:{obj_id}"

    async def get(self, table_name: str, obj_id: any):
        """Keshdan ma'lumotni olish"""
        key = self._get_key(table_name, obj_id)
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def set(self, obj, expire: int = 3600):
        """Obyektni keshga saqlash (Default: 1 soat)"""
        # Obyektni dict-ga o'tkazish (faqat oddiy ustunlarni)
        mapper = inspect(obj).mapper
        data = {
            c.key: getattr(obj, c.key) 
            for c in mapper.column_attrs 
            if not isinstance(getattr(obj, c.key), (bytes, datetime))
        }
        
        # Primary key-ni olish
        pk_name = mapper.primary_key[0].name
        pk_value = getattr(obj, pk_name)
        
        key = self._get_key(obj.__tablename__, pk_value)
        await self.redis.set(key, json.dumps(data, default=str), ex=expire)

    async def invalidate(self, table_name: str, obj_id: any):
        """Keshni o'chirish"""
        key = self._get_key(table_name, obj_id)
        await self.redis.delete(key)

# Sizning Valkey URL-manzilingiz
VALKEY_URL = "rediss://default:AVNS_we2yEcP5dUSuNSGfEOi@valkey-aninovuzbot-xudoyqulovabdulaziz08-0be3.h.aivencloud.com:27625"
valkey = CacheManager(VALKEY_URL)