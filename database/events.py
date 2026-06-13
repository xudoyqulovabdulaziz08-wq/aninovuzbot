import logging
import hashlib
import json
import zlib
from uuid import uuid4
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from sqlalchemy import event, inspect, select
from sqlalchemy.engine import Connection

from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")

# ================= CONFIG =================
ENABLE_COMPRESSION = True  
ENABLE_DEDUP = True        
SLOW_EVENT_THRESHOLD_MS = 50  


# ================= SAFE PRIMARY KEY EXTRACTION =================
def get_pk_value(target: Any, state: Optional[Any] = None) -> Optional[str]:
    try:
        obj_state = state or inspect(target)
        mapper = obj_state.mapper
        pk_values = []
        for col in mapper.primary_key:
            # Detached yoki o'chirilgan holatda keshdan olish xavfsizroq
            if obj_state.detached or obj_state.deleted:
                val = obj_state.attrs[col.key].value
            else:
                val = getattr(target, col.key)
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


# ================= DEDUP HASH =================
def make_event_hash(table: str, pk: str, event_type: str, raw_payload: Dict[str, Any]) -> str:
    serialized_payload = json.dumps(raw_payload, sort_keys=True, ensure_ascii=False)
    raw = f"{table}:{pk}:{event_type}:{serialized_payload}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


# ================= RAW PAYLOAD BUILDER =================
def build_raw_payload(target: Any, state: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    try:
        data = {}
        obj_state = state or inspect(target)
        
        for col in obj_state.mapper.column_attrs:
            key = col.key
            if obj_state.deleted or obj_state.detached:
                val = obj_state.attrs[key].value
            else:
                val = getattr(target, key)

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


# ================= COMPRESS ENGINE =================
def compress_payload(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_str = json.dumps(raw_payload, ensure_ascii=False)
    compressed_hex = zlib.compress(raw_str.encode('utf-8'), level=6).hex()
    return {
        "is_compressed": True,
        "data": compressed_hex  
    }


# ================= CORE HANDLER ENGINE =================
def emit_outbox_event(
    connection: Connection, 
    target: Any, 
    event_type: str, 
    pre_built_raw_payload: Optional[Dict[str, Any]] = None,
    pre_built_pk: Optional[str] = None
):
    start = datetime.now(timezone.utc)
    table = getattr(target, "__tablename__", "unknown")
    
    try:
        # O'chirilgan obyektlar uchun PK oldindan uzatiladi, aks holda joyida aniqlaymiz
        pk_val = pre_built_pk or get_pk_value(target)
        if not pk_val:
            return

        if event_type == "update" and not has_real_changes(target):
            return

        raw_payload = pre_built_raw_payload or build_raw_payload(target)
        if raw_payload is None:
            logger.error(f"❌ Payload build failed, outbox skipped for {table}:{pk_val}")
            return

        event_hash = None
        if ENABLE_DEDUP:
            event_hash = make_event_hash(table, pk_val, event_type, raw_payload)
            
            # Unprocessed bo'lgan aynan shu hashni tekshirish
            dup_stmt = select(OutboxEvent.__table__.c.id).where(
                OutboxEvent.__table__.c.event_hash == event_hash,
                OutboxEvent.__table__.c.processed == False
            )
            if connection.execute(dup_stmt).first():
                return  

        final_payload = compress_payload(raw_payload) if ENABLE_COMPRESSION else raw_payload
        payload_str = json.dumps(final_payload, ensure_ascii=False)

        stmt = OutboxEvent.__table__.insert().values(
            id=str(uuid4()),
            aggregate=table,
            aggregate_id=pk_val,
            event_type=event_type,
            payload=payload_str,  
            event_hash=event_hash,
            processed=False,
            retry_count=0,
            created_at=datetime.now(timezone.utc)
        )

        # 🚨 SAVEPOINT PROTECTION
        nested = connection.begin_nested()
        try:
            connection.execute(stmt)
            nested.commit()
        except Exception as db_err:
            nested.rollback()  
            # IntegrityError (Masalan unique index buzilsa) sodir bo'lishi mumkin, log qilamiz
            logger.warning(f"⚠️ Outbox INSERT ignored due to DB constraint/error: {db_err}")
            return

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        if duration > SLOW_EVENT_THRESHOLD_MS:
            logger.warning(
                f"⚠️ SLOW OUTBOX EVENT: {table} -> [{event_type}] {duration:.2f}ms cho'zildi."
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
                # O'chishidan oldindan PK va Payloadni xavfsiz holatda yig'ib qo'yamiz
                target._outbox_pre_delete_raw_payload = build_raw_payload(target)
                target._outbox_pre_delete_pk = get_pk_value(target)
            except Exception as e:
                logger.error(f"❌ Pre-delete data capture failed: {e}")
                target._outbox_pre_delete_raw_payload = None
                target._outbox_pre_delete_pk = None
        elif event_type == "after_delete":
            payload = getattr(target, "_outbox_pre_delete_raw_payload", None)
            pk = getattr(target, "_outbox_pre_delete_pk", None)
            emit_outbox_event(connection, target, "delete", pre_built_raw_payload=payload, pre_built_pk=pk)

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

        logger.info(f"🚀 [Outbox System Engine] yuklandi: {count} ta model ulandi.")

    except Exception as e:
        logger.critical(f"❌ [Outbox System Engine] ulanishda kritik xato: {e}")