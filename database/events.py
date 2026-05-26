import logging
import hashlib
import json
import zlib
from uuid import uuid4, UUID  # ➕ UUID import qilindi
from decimal import Decimal    # ➕ Decimal import qilindi
from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection

from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")


# ================= CONFIG =================
ENABLE_COMPRESSION = True  # 💡 Yoqilgan holatda ham endi xavfsiz ishlaydi
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
def make_event_hash(table: str, pk: str, event_type: str, payload: dict) -> str:
    # 💡 Payload endi dict bo'lgani uchun uni string qilib hashlaymiz
    raw = f"{table}:{pk}:{event_type}:{json.dumps(payload)}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ================= PAYLOAD BUILDER =================
def build_payload(target) -> dict:  # 🚨 FIX: String emas, DOIM dict (lug'at) qaytaradi
    try:
        data = {}

        for col in inspect(target).mapper.column_attrs:
            key = col.key
            val = getattr(target, key)

            # 🔥 FIX: Barcha maxsus ma'lumot turlarini JSON bop holatga keltiramiz
            if isinstance(val, datetime):
                val = val.isoformat()
            elif isinstance(val, Decimal):
                val = float(val)  # Decimal ni float ga o'giramiz
            elif isinstance(val, UUID):
                val = str(val)    # UUID ni string ga o'giramiz

            data[key] = val

        # 🔥 FIX: Agar siqish (compression) yoqilgan bo'lsa, uni lug'at ichiga joylaymiz!
        if ENABLE_COMPRESSION:
            raw_str = json.dumps(data, ensure_ascii=False)
            compressed_hex = zlib.compress(raw_str.encode(), level=6).hex()
            return {
                "is_compressed": True,
                "data": compressed_hex  # Worker buni ochganda srazu zlib.decompress qiladi
            }

        return data  # Toza Python lug'ati (dict)

    except Exception as e:
        logger.warning(f"Payload build failed: {e}")
        return {"error": "serialization_failed"}  # Doim valid dict qaytishi shart


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

            payload_dict = build_payload(target)  # Obyekt lug'at shaklida keladi

            event_hash = None
            if ENABLE_DEDUP:
                event_hash = make_event_hash(table, pk_val, event_type, payload_dict)

            # 🚨 ENG MUHIM FIX: values() ichida payloadga toza dict beryapmiz. 
            # SQLAlchemy buni o'zi bazaga to'g'ri JSON/JSONB formatida yozadi.
            stmt = OutboxEvent.__table__.insert().values(
                id=str(uuid4()),
                aggregate=table,
                aggregate_id=pk_val,
                event_type=event_type,
                payload=payload_dict,  # 👈 TO'G'RILANDI (Dict)
                processed=False,
                retry_count=0,
                created_at=datetime.now(timezone.utc)
            )

            connection.execute(stmt)

            # performance log
            duration = (datetime.now() - start).total_seconds() * 1000

            if duration > SLOW_EVENT_THRESHOLD_MS:
                logger.warning(
                    f"Core Outbox System: {table} "
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