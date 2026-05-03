import logging
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection

from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")


# ================= PK SAFE =================
def get_pk_value(target) -> str | None:
    try:
        mapper = inspect(target).mapper
        pk_values = [
            str(getattr(target, col.key))
            for col in mapper.primary_key
        ]
        return ":".join(pk_values)
    except Exception as e:
        logger.error(f"PK extraction failed [{target}]: {e}")
        return None


# ================= CHANGE DETECTOR =================
def has_real_changes(target) -> bool:
    """Update bo‘lsa, haqiqiy o‘zgarish borligini tekshiradi"""
    state = inspect(target)

    for attr in state.attrs:
        if attr.history.has_changes():
            return True
    return False


# ================= PAYLOAD BUILDER =================
def build_payload(target) -> str:
    """Minimal JSON payload"""
    try:
        data = {}

        for col in inspect(target).mapper.column_attrs:
            key = col.key
            val = getattr(target, key)

            # JSON serializable qilish
            if isinstance(val, datetime):
                val = val.isoformat()

            data[key] = val

        import orjson
        return orjson.dumps(data).decode()

    except Exception as e:
        logger.warning(f"Payload build failed: {e}")
        return "{}"


# ================= MAIN HANDLER =================
def on_model_change(event_type: str):
    def handler(mapper, connection: Connection, target):

        pk_val = get_pk_value(target)
        if not pk_val:
            return

        # UPDATE bo‘lsa — real change tekshirish
        if event_type == "update" and not has_real_changes(target):
            return

        try:
            payload = build_payload(target)

            stmt = OutboxEvent.__table__.insert().values(
                id=str(uuid4()),
                aggregate=target.__tablename__,
                aggregate_id=pk_val,
                event_type=event_type,
                payload=payload,
                processed=False,
                created_at=datetime.now(timezone.utc)
            )

            connection.execute(stmt)

        except Exception as e:
            # ⚠️ Bu yerda exception tashlamaymiz — systemni yiqitmaymiz
            logger.error(
                f"Outbox write failed [{event_type}] {target.__tablename__}: {e}"
            )

    return handler


# ================= ATTACH =================
def attach_cache_listeners():
    for model in MODELS_TO_WATCH:
        event.listen(model, "after_insert", on_model_change("insert"))
        event.listen(model, "after_update", on_model_change("update"))
        event.listen(model, "after_delete", on_model_change("delete"))

    logger.info(f"✅ Outbox listeners attached: {len(MODELS_TO_WATCH)} models")