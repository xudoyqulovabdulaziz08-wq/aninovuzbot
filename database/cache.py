import json
import asyncio
from datetime import datetime
import redis.asyncio as redis
from sqlalchemy import inspect
from config import config

class CacheManager:
    def __init__(self, url: str):
        self.redis = redis.from_url(
            url, 
            decode_responses=True,
            # Ulanish vaqtini cheklaymiz, bot qotib qolmasligi uchun
            socket_timeout=2.0, 
            socket_connect_timeout=2.0,
            retry_on_timeout=True
        )

    def _get_key(self, table_name: str, obj_id):
        return f"{table_name}:{obj_id}"

    async def get(self, table_name: str, obj_id):
        """Keshdan ma'lumotni olish (Timeout bilan)"""
        try:
            key = self._get_key(table_name, obj_id)
            # 1 soniyadan ko'p kutmaymiz
            data = await asyncio.wait_for(self.redis.get(key), timeout=1.0)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"⚠️ Keshni o'qishda xatolik: {e}")
            return None

    async def set(self, obj, expire: int = 3600):
        """Obyektni keshga saqlash (SQLAlchemy modeli uchun)"""
        if obj is None: return

        try:
            state = inspect(obj)
            if not state: return
            
            mapper = state.mapper
            data = {}
            for c in mapper.column_attrs:
                value = getattr(obj, c.key)
                # None qiymatlarni str("None") qilmaslik uchun tekshiruv
                if value is None:
                    data[c.key] = None
                elif isinstance(value, (datetime, bytes)):
                    data[c.key] = str(value)
                else:
                    data[c.key] = value

            pk_name = mapper.primary_key[0].name
            pk_value = getattr(obj, pk_name)
            key = self._get_key(obj.__tablename__, pk_value)
        
            await asyncio.wait_for(
                self.redis.set(key, json.dumps(data, default=str), ex=expire),
                timeout=1.0
            )
        except Exception as e:
            print(f"⚠️ Keshga yozishda xatolik: {e}")

    async def set_custom(self, key: str, data: any, expire: int = 600):
        """Ixtiyoriy ma'lumotni keshga saqlash"""
        try:
            await asyncio.wait_for(
                self.redis.set(key, json.dumps(data, default=str), ex=expire),
                timeout=1.0
            )
        except:
            pass

    async def invalidate(self, table_name: str, obj_id):
        """Keshni o'chirish"""
        try:
            key = self._get_key(table_name, obj_id)
            await self.redis.delete(key)
        except:
            pass

# ✅ URL .env faylidan olinadi
VALKEY_URL = config.VALKEY_URL
valkey = CacheManager(VALKEY_URL)