from sqlalchemy import event
import redis  # Sinxron redis eventlar uchun kerak bo'lishi mumkin
from database.cache import valkey, VALKEY_URL  # Asinxron cache manager

# Sinxron ulanish (SQLAlchemy eventlari sinxron bo'lgani uchun)
sync_redis = redis.from_url(VALKEY_URL)

def attach_cache_listener(target_class):
    @event.listens_for(target_class, 'after_update')
    @event.listens_for(target_class, 'after_delete')
    def clear_cache(mapper, connection, target):
        pk_name = mapper.primary_key[0].name
        obj_id = getattr(target, pk_name)
        key = f"{target.__tablename__}:{obj_id}"
        sync_redis.delete(key)
        print(f"🔥 Kesh o'chirildi: {key}")

# Hamma modellarga ulab chiqamiz
from database.models import DBUser, Anime, Genre, Episode, Comment, Favorite, History, Ticket, Channel, HelpPage, FanGroup, Advertisement, AdminSettings # va h.k.
models_to_watch = [DBUser, Anime, Genre, Episode, Comment, Favorite, History, Ticket, Channel, HelpPage, FanGroup, Advertisement, AdminSettings]  # Keshni kuzatmoqchi bo'lgan modellaringizni shu yerga qo'shing

for model in models_to_watch:
    attach_cache_listener(model)