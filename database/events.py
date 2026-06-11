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

# Modellaringiz joylashgan paketdan import qilinadi
from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")

# ================= CONFIG =================
ENABLE_COMPRESSION = True  # Worker tomonda decompress qilinadi
ENABLE_DEDUP = True        # Takroriy xabarlarni filtrlash (Deduplication)
SLOW_EVENT_THRESHOLD_MS = 50  # Tranzaksiya ichida 50ms dan oshsa ogohlantiradi


# ================= SAFE PRIMARY KEY EXTRACTION =================
def get_pk_value(target: Any, state: Optional[Any] = None) -> Optional[str]:
    try:
        obj_state = state or inspect(target)
        mapper = obj_state.mapper
        pk_values = []
        for col in mapper.primary_key:
            # Agarda obyekt o'chirilgan bo'lsa, xavfsiz holatda keshdan yoki atributdan olamiz
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
        # Agar obyekt yangi bo'lsa yoki o'chirilayotgan bo'lsa, tekshirish shart emas
        if state.transient or state.deleted:
            return True
            
        for attr in state.attrs:
            if attr.history.has_changes():
                return True
        return False
    except Exception as e:
        logger.error(f"❌ Change detect error: {e}")
        return True  # Xato bo'lsa xavfsizlik uchun o'zgargan deb hisoblaymiz


# ================= DEDUP HASH =================
def make_event_hash(table: str, pk: str, event_type: str, raw_payload: Dict[str, Any]) -> str:
    """
    💡 Hash doim siqilmagan (RAW) payload bo'yicha hisoblanadi.
    sort_keys=True yordamida deterministik string yaratiladi.
    """
    serialized_payload = json.dumps(raw_payload, sort_keys=True, ensure_ascii=False)
    raw = f"{table}:{pk}:{event_type}:{serialized_payload}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ================= RAW PAYLOAD BUILDER =================
def build_raw_payload(target: Any, state: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """
    Faqat toza (raw) Python lug'atini yig'adi.
    Exception holatida dict emas, None qaytaradi.
    """
    try:
        data = {}
        obj_state = state or inspect(target)
        
        for col in obj_state.mapper.column_attrs:
            key = col.key
            if obj_state.deleted or obj_state.detached:
                val = obj_state.attrs[key].value
            else:
                val = getattr(target, key)

            # 🔥 Maxsus ma'lumot turlarini JSON-safe formatga o'giramiz
            if isinstance(val, datetime):
                data[key] = val.isoformat()
            elif isinstance(val, Decimal):
                data[key] = str(val)  # float o'rniga str (Aniqlik yo'qolmaydi!)
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
    """
    Toza payloadni meta-dict ichiga siqib beradi.
    """
    raw_str = json.dumps(raw_payload, ensure_ascii=False)
    compressed_hex = zlib.compress(raw_str.encode(), level=6).hex()
    return {
        "is_compressed": True,
        "data": compressed_hex  # Worker buni zlib.decompress qiladi
    }


# ================= CORE HANDLER ENGINE =================
def emit_outbox_event(connection: Connection, target: Any, event_type: str, pre_built_raw_payload: Optional[Dict[str, Any]] = None):
    """
    Yagona va xavfsiz Outbox yozish funksiyasi. Savepoint va to'liq izolyatsiya bilan.
    """
    start = datetime.now(timezone.utc)  # Izchil Timezone (UTC)
    table = getattr(target, "__tablename__", "unknown")
    state = inspect(target)
    
    try:
        pk_val = get_pk_value(target, state=state)
        if not pk_val:
            return

        # Empty update'larni o'tkazib yuborish
        if event_type == "update" and not has_real_changes(target):
            return

        # 1. Toza (raw) payloadni olish yoki qurish
        raw_payload = pre_built_raw_payload or build_raw_payload(target, state=state)
        
        if raw_payload is None:
            logger.error(f"❌ Payload build failed, outbox skipped for {table}:{pk_val}")
            return

        # 2. Dedup HASH siqishdan oldin toza ma'lumotdan olinadi
        event_hash = None
        if ENABLE_DEDUP:
            event_hash = make_event_hash(table, pk_val, event_type, raw_payload)
            
            # 🌟 ORA-OPTIMIZATION: Agar xuddi shu xabar bazada hali qayta ishlanmagan bo'lsa, dual insert qilmaymiz
            dup_stmt = select(OutboxEvent.__table__.c.id).where(
                OutboxEvent.__table__.c.event_hash == event_hash,
                OutboxEvent.__table__.c.processed == False
            )
            if connection.execute(dup_stmt).first():
                return  # Allaqachon navbatda bor, ortiqcha yuklamaslik uchun chiqib ketamiz

        # 3. Agar siqish yoqilgan bo'lsa, bazaga yozishdan oldin siqamiz
        final_payload = compress_payload(raw_payload) if ENABLE_COMPRESSION else raw_payload

        # 🌟 CRITICAL ORACLE FIX: Core table darajasida insert qilinayotgani va ustun Text (CLOB) bo'lgani uchun,
        # final_payload (dict) obyektini mantiqan to'g'ri string (JSON format) qilib yuborish shart!
        payload_str = json.dumps(final_payload, ensure_ascii=False)

        stmt = OutboxEvent.__table__.insert().values(
            id=str(uuid4()),
            aggregate=table,
            aggregate_id=pk_val,
            event_type=event_type,
            payload=payload_str,  # <-- Lug'at o'rniga JSON string berildi!
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
            nested.rollback()  # Faqat Outbox INSERT o'chadi, asosiy biznes oqimi saqlanadi
            raise db_err

        # Performance Monitoring
        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        if duration > SLOW_EVENT_THRESHOLD_MS:
            logger.warning(
                f"⚠️ SLOW OUTBOX EVENT: {table} -> [{event_type}] bajarilishi {duration:.2f}ms cho'zildi."
            )

    except Exception as e:
        logger.error(
            f"❌ Outbox write fully isolated & skipped [{event_type}] on table '{table}': {e}"
        )


# ================= HOOK LISTENERS (DUPLICATE SAFE) =================
_handlers = {}  # Handlerlarni xotirada keshda saqlash uchun lug'at

def get_or_create_handlers(event_type: str):
    """
    Sinxron SQLAlchemy oqimi uchun har bir event_type bo'yicha 
    yagona identifikatorga ega handlerlarni yetkazib beradi.
    """
    def closure_handler(mapper: Any, connection: Connection, target: Any):
        if event_type == "insert":
            emit_outbox_event(connection, target, "insert")
        elif event_type == "update":
            emit_outbox_event(connection, target, "update")
        elif event_type == "before_delete":
            try:
                state = inspect(target)
                # O'chishidan oldin toza payloadni obyektdagi vaqtinchalik o'zgaruvchiga bog'laymiz
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
    """
    🚀 Modellar uchun mukammal Outbox oqimlarini ulash tizimi.
    Idempotent: Ko'p marta chaqirilsa ham duplicate listenerlar ulamaydi!
    """
    try:
        count = 0
        for model in MODELS_TO_WATCH:
            # Agar model allaqachon tinglanayotgan bo'lsa, tashlab ketamiz
            if model in _handlers:
                continue

            # Handlerlarni faqat bir marta yaratib, keshga saqlaymiz
            handlers = {
                "insert": get_or_create_handlers("insert"),
                "update": get_or_create_handlers("update"),
                "before_delete": get_or_create_handlers("before_delete"),
                "after_delete": get_or_create_handlers("after_delete"),
            }
            _handlers[model] = handlers

            event.listen(model, "after_insert", handlers["insert"])
            event.listen(model, "after_update", handlers["update"])
            
            # O'chirish hodisalari zanjiri (DetachedInstanceError oldini balanslash)
            event.listen(model, "before_delete", handlers["before_delete"])
            event.listen(model, "after_delete", handlers["after_delete"])
            count += 1

        logger.info(f"🚀 [Outbox System Engine] yuklandi: {count} ta model takrorlanishdan (Duplicate) himoyalangan holda ulandi.")

    except Exception as e:
        logger.critical(f"❌ [Outbox System Engine] modellar tinglovchilarini ulashda kritik xato: {e}")