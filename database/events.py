import logging
import hashlib
import json
import zlib
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection

from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")


# ================= CONFIG =================
ENABLE_COMPRESSION = True
ENABLE_DEDUP = True
SLOW_EVENT_THRESHOLD_MS = 20


# ================= SAFE PK =================
def get_pk_value(target) -> str | None:
    try:
        mapper = inspect(target).mapper
        pk_values = [
            str(getattr(target, col.key))
            for col in mapper.primary_key
        ]
        return ":".join(pk_values)
    except Exception as e:
        logger.error(f"PK extraction failed: {e}")
        return None


# ================= CHANGE DETECTOR =================
def has_real_changes(target) -> bool:
    try:
        state = inspect(target)

        for attr in state.attrs:
            if attr.history.has_changes():
                return True

        return False
    except Exception as e:
        logger.error(f"Change detect error: {e}")
        return False


# ================= DEDUP HASH =================
def make_event_hash(table: str, pk: str, event_type: str, payload: str) -> str:
    raw = f"{table}:{pk}:{event_type}:{payload}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ================= PAYLOAD BUILDER =================
def build_payload(target) -> str:
    try:
        data = {}

        for col in inspect(target).mapper.column_attrs:
            key = col.key
            val = getattr(target, key)

            if isinstance(val, datetime):
                val = val.isoformat()

            data[key] = val

        raw = json.dumps(data, ensure_ascii=False)

        # optional compression
        if ENABLE_COMPRESSION:
            compressed = zlib.compress(raw.encode(), level=6)
            return compressed.hex()

        return raw

    except Exception as e:
        logger.warning(f"Payload build failed: {e}")
        return "{}"


# ================= CORE HANDLER =================
def on_model_change(event_type: str):
    def handler(mapper, connection: Connection, target):

        start = datetime.now()

        try:
            table = target.__tablename__
            pk_val = get_pk_value(target)

            if not pk_val:
                return

            # ignore empty updates
            if event_type == "update" and not has_real_changes(target):
                return

            payload = build_payload(target)

            event_hash = None
            if ENABLE_DEDUP:
                event_hash = make_event_hash(table, pk_val, event_type, payload)

            stmt = OutboxEvent.__table__.insert().values(
                id=str(uuid4()),
                aggregate=table,
                aggregate_id=pk_val,
                event_type=event_type,
                payload=payload,
                processed=False,
                retry_count=0,
                created_at=datetime.now(timezone.utc)
            )

            connection.execute(stmt)

            # performance log
            duration = (datetime.now() - start).total_seconds() * 1000

            if duration > SLOW_EVENT_THRESHOLD_MS:
                logger.warning(
                    f"🐢 Slow event write: {table} "
                    f"{event_type} {duration:.2f}ms"
                )

        except Exception as e:
            # NEVER break transaction
            logger.error(
                f"Outbox write failed [{event_type}] "
                f"{getattr(target, '__tablename__', 'unknown')}: {e}"
            )

    return handler


# ================= ATTACH LISTENERS =================
def attach_cache_listeners():
    try:
        count = 0

        for model in MODELS_TO_WATCH:
            event.listen(model, "after_insert", on_model_change("insert"))
            event.listen(model, "after_update", on_model_change("update"))
            event.listen(model, "after_delete", on_model_change("delete"))
            count += 1

        logger.info(f"🚀 Outbox system ready: {count} models")

    except Exception as e:
        logger.critical(f"Outbox attach failed: {e}")