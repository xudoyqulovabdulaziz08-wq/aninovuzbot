import json
from datetime import datetime
import redis.asyncio as redis
from sqlalchemy import inspect
from config import config


class CacheManager:
    def __init__(self, url: str):
        self.redis = redis.from_url(url, decode_responses=True)
        # Ulanishni tekshirish uchun flag
        self.is_connected = False

    async def connect(self):
        """Redis bilan aloqani tekshirish"""
        try:
            await self.redis.ping()
            self.is_connected = True
            print("✅ Valkey (Redis) kesh bazasiga muvaffaqiyatli ulanildi!")
        except Exception as e:
            self.is_connected = False
            print(f"❌ Valkey (Redis) ulanishida xatolik: {e}")

    def _get_key(self, table_name: str, obj_id):
        return f"{table_name}:{obj_id}"

    async def get(self, table_name: str, obj_id):
        """Keshdan ma'lumotni olish"""
        key = self._get_key(table_name, obj_id)
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def set(self, obj, expire: int = 3600):
        """Obyektni keshga saqlash (SQLAlchemy modeli uchun)"""
        # Agar obyekt model emas, dict bo'lsa inspect ishlamaydi
        if isinstance(obj, dict) or obj is None:
            return

        try:
            from sqlalchemy import inspect
            state = inspect(obj)
            if state is None:
                return
            
            mapper = state.mapper
            # Faqat JSON qila oladigan ma'lumotlarni ajratib olamiz
            data = {}
            for c in mapper.column_attrs:
                value = getattr(obj, c.key)
                    # datetime va boshqa murakkab turlarni stringga aylantiramiz
                if isinstance(value, (datetime, bytes)):
                    data[c.key] = str(value)
                else:
                    data[c.key] = value

            pk_name = mapper.primary_key[0].name
            pk_value = getattr(obj, pk_name)
            key = self._get_key(obj.__tablename__, pk_value)
        
            await self.redis.set(key, json.dumps(data, default=str), ex=expire)
        except Exception as e:
            print(f"⚠️ Keshga saqlashda xatolik: {e}")
    
    async def set_custom(self, key: str, data: any, expire: int = 600):
        """Ixtiyoriy ma'lumotni keshga saqlash"""
        await self.redis.set(key, json.dumps(data, default=str), ex=expire)

    async def invalidate(self, table_name: str, obj_id):
        """Keshni o'chirish"""
        key = self._get_key(table_name, obj_id)
        await self.redis.delete(key)
    # CacheManager ichiga qo'shib qo'ying


# ✅ URL .env faylidan olinadi (credentials GitHub'da ko'rinmaydi)
VALKEY_URL = config.VALKEY_URL
valkey = CacheManager(VALKEY_URL)