import logging
import hashlib
import json
import zlib
from uuid import uuid4
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection

# Modellaringiz joylashgan paketdan import qilinadi
from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")

# ================= CONFIG =================
ENABLE_COMPRESSION = True  
ENABLE_DEDUP = True        
SLOW_EVENT_THRESHOLD_MS = 50  
COMPRESSION_THRESHOLD_BYTES = 1024  # 🔥 OPTIMIZATSIYA: 1KB dan kichik payloadlarni siqib CPU ni qiynamaymiz!


# ================= SAFE PRIMARY KEY EXTRACTION =================
def get_pk_value(target: Any, state: Optional[Any] = None) -> Optional[str]:
    try:
        obj_state = state or inspect(target)
        mapper = obj_state.mapper
        pk_values = []
        for col in mapper.primary_key:
            val = obj_state.attrs[col.key].value if obj_state.detached else getattr(target, col.key)
            pk_values.append(str(val))
        return ":".join(pk_values)
    except Exception as e:
        logger.error(f"❌ PK extraction failed: {e}")
        return None


# ================= CHANGE DETECTOR =================
def has_real_changes(target: Any) -> bool:
    try:
        state = inspect(target)
        if state.transient or state.deleted:
            return True
            
        for attr in state.attrs:
            if attr.history.has_changes():
                return True
        return False
    except Exception as e:
        logger.error(f"❌ Change detect error: {e}")
        return True


# ================= RAW PAYLOAD BUILDER =================
def build_raw_payload(target: Any, state: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    try:
        data = {}
        obj_state = state or inspect(target)
        
        for col in obj_state.mapper.column_attrs:
            key = col.key
            val = obj_state.attrs[key].value if (obj_state.deleted or obj_state.detached) else getattr(target, key)

            if isinstance(val, datetime):
                data[key] = val.isoformat()
            elif isinstance(val, Decimal):
                data[key] = str(val)  
            elif val.__class__.__name__ == 'UUID':
                data[key] = str(val)
            else:
                data[key] = val

        return data
    except Exception as e:
        logger.warning(f"⚠️ Raw payload build failed: {e}")
        return None


# ================= CORE HANDLER ENGINE =================
def emit_outbox_event(connection: Connection, target: Any, event_type: str, pre_built_raw_payload: Optional[Dict[str, Any]] = None):
    """
    Yagona va xavfsiz Outbox yozish funksiyasi. 
    CPU-bound operatsiyalar (zlib, json) maksimal darajada optimallashtirildi.
    """
    start = datetime.now(timezone.utc)
    table = getattr(target, "__tablename__", "unknown")
    state = inspect(target)
    
    try:
        pk_val = get_pk_value(target, state=state)
        if not pk_val:
            return

        if event_type == "update" and not has_real_changes(target):
            return

        raw_payload = pre_built_raw_payload or build_raw_payload(target, state=state)
        if raw_payload is None:
            logger.error(f"❌ Payload build failed, outbox skipped for {table}:{pk_val}")
            return

        # 🔥 OPTIMIZATSIYA 1: JSON serializatsiyani faqat 1 marta bajaramiz!
        # sort_keys=True ham Dedup Hash uchun, ham siqish uchun yagona deterministik string beradi
        raw_str = json.dumps(raw_payload, sort_keys=True, ensure_ascii=False)
        raw_bytes = raw_str.encode('utf-8')

        # 1. Dedup HASH hisoblash
        event_hash = None
        if ENABLE_DEDUP:
            raw_hash_base = f"{table}:{pk_val}:{event_type}:{raw_str}"
            event_hash = hashlib.sha256(raw_hash_base.encode('utf-8')).hexdigest()

        # 2. Aqlli Siqish Tizimi (Smart Compression)
        # 🔥 OPTIMIZATSIYA 2: Faqat ma'lumot hajmi belgilangan chegaradan katta bo'lsa va level=3 (Tezkor) rejimda siqiladi
        if ENABLE_COMPRESSION and len(raw_bytes) > COMPRESSION_THRESHOLD_BYTES:
            compressed_hex = zlib.compress(raw_bytes, level=3).hex()  # level 6 dan 3 ga tushirildi (CPU yukini 3 barobarga kamaytiradi)
            final_payload = {
                "is_compressed": True,
                "data": compressed_hex
            }
        else:
            final_payload = raw_payload  # Kichik ma'lumotlar asl holida qoladi

        stmt = OutboxEvent.__table__.insert().values(
            id=str(uuid4()),
            aggregate=table,
            aggregate_id=pk_val,
            event_type=event_type,
            payload=final_payload,
            event_hash=event_hash,
            processed=False,
            retry_count=0,
            created_at=datetime.now(timezone.utc)
        )

        # 🚨 TRANSACTION SAFETY (SAVEPOINT PROTECTION)
        nested = connection.begin_nested()
        try:
            connection.execute(stmt)
            nested.commit()
        except Exception as db_err:
            nested.rollback()
            raise db_err

        # Performance Monitoring
        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        if duration > SLOW_EVENT_THRESHOLD_MS:
            logger.warning(
                f"⚠️ [SLOW OUTBOX ALERT] {table} -> [{event_type}] bajarilishi {duration:.2f}ms cho'zildi! Protsessor yoki DB yuklanishini tekshiring."
            )

    except Exception as e:
        logger.error(
            f"❌ Outbox write fully isolated & skipped [{event_type}] on table '{table}': {e}"
        )


# ================= HOOK LISTENERS (DUPLICATE SAFE) =================
_handlers = {}

def get_or_create_handlers(event_type: str):
    def closure_handler(mapper: Any, connection: Connection, target: Any):
        if event_type == "insert":
            emit_outbox_event(connection, target, "insert")
        elif event_type == "update":
            emit_outbox_event(connection, target, "update")
        elif event_type == "before_delete":
            try:
                state = inspect(target)
                target._outbox_pre_delete_raw_payload = build_raw_payload(target, state=state)
            except Exception as e:
                logger.error(f"❌ Pre-delete payload capture failed: {e}")
                target._outbox_pre_delete_raw_payload = None
        elif event_type == "after_delete":
            payload = getattr(target, "_outbox_pre_delete_raw_payload", None)
            emit_outbox_event(connection, target, "delete", pre_built_raw_payload=payload)

    return closure_handler


# ================= ATTACH LISTENERS =================
def attach_cache_listeners():
    try:
        count = 0
        for model in MODELS_TO_WATCH:
            if model in _handlers:
                continue

            handlers = {
                "insert": get_or_create_handlers("insert"),
                "update": get_or_create_handlers("update"),
                "before_delete": get_or_create_handlers("before_delete"),
                "after_delete": get_or_create_handlers("after_delete"),
            }
            _handlers[model] = handlers

            event.listen(model, "after_insert", handlers["insert"])
            event.listen(model, "after_update", handlers["update"])
            event.listen(model, "before_delete", handlers["before_delete"])
            event.listen(model, "after_delete", handlers["after_delete"])
            count += 1

        logger.info(f"🚀 [Outbox System Engine] yuklandi: {count} ta model takrorlanishdan himoyalangan holda ulandi.")

    except Exception as e:
        logger.critical(f"❌ [Outbox System Engine] modellar tinglovchilarini ulashda kritik xato: {e}")