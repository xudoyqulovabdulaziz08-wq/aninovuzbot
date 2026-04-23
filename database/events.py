import redis
import logging
from sqlalchemy import event
from database.cache import VALKEY_URL
from database.models import (
    DBUser, Anime, Genre, Episode, Comment, Favorite,
    History, Ticket, Channel, HelpPage, FanGroup,
    Advertisement, AdminSettings
)

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("CacheSystem")

# ================= REDIS (SAFE) =================
sync_redis = redis.from_url(
    VALKEY_URL,
    socket_timeout=1,
    socket_connect_timeout=1,
    retry_on_timeout=True,
    decode_responses=True
)

CACHE_VERSION = "v1"


# ================= PK EXTRACTOR =================
def get_pk_value(target):
    """Universal PK extractor (supports composite keys)."""
    try:
        mapper = target.__mapper__
        pk_values = [getattr(target, col.key) for col in mapper.primary_key]
        return ":".join(str(v) for v in pk_values)
    except Exception as e:
        logger.error(f"PK extraction failed for {target.__class__.__name__}: {e}")
        return None


# ================= CACHE INVALIDATION =================
def clear_valkey_cache(target):
    """
    Safe cache invalidation layer.
    DB NEVER affected even if Redis fails.
    """
    pk_val = get_pk_value(target)
    if not pk_val:
        return

    table_name = target.__tablename__

    obj_key = f"{table_name}:{pk_val}:obj:{CACHE_VERSION}"

    try:
        pipe = sync_redis.pipeline()
        pipe.delete(obj_key)

        # special cases
        if table_name == "anime_list":
            pipe.delete(f"anime_list:all:list:{CACHE_VERSION}")

        pipe.execute()

        logger.info(f"Cache invalidated: {obj_key}")

    except redis.exceptions.RedisError as e:
        logger.warning(f"Redis unavailable, skipping cache invalidation: {e}")


# ================= MODELS REGISTRY =================
MODELS_TO_WATCH = [
    DBUser, Anime, Genre, Episode,
    Comment, Favorite, History, Ticket,
    Channel, HelpPage, FanGroup,
    Advertisement, AdminSettings
]


# ================= EVENT BINDING =================
def attach_cache_invalidation_listener(model_class):
    """
    Bind SQLAlchemy events to cache invalidation.
    Lightweight event layer (no heavy logic here).
    """

    @event.listens_for(model_class, "after_update")
    @event.listens_for(model_class, "after_delete")
    def on_model_change(mapper, connection, target):
        clear_valkey_cache(target)


# ================= INIT =================
for model in MODELS_TO_WATCH:
    attach_cache_invalidation_listener(model)