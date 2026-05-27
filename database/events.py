import logging
import hashlib
import json
import zlib
from uuid import uuid4, UUID
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection

# Modellaringiz joylashgan paketdan import qilinadi
from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")


# ================= CONFIG =================
ENABLE_COMPRESSION = True  # Yoqilgan holatda ham xavfsiz ishlaydi (Worker tomonda decompress qilinadi)
ENABLE_DEDUP = True        # Takroriy xabarlarni filtrlash (Deduplication)
SLOW_EVENT_THRESHOLD_MS = 20


# ================= SAFE PRIMARY KEY EXTRACTION =================
def get_pk_value(target: Any) -> Optional[str]:
    try:
        mapper = inspect(target).mapper
        pk_values = [
            str(getattr(target, col.key))
            for col in mapper.primary_key
        ]
        return ":".join(pk_values)
    except Exception as e:
        logger.error(f"❌ PK extraction failed: {e}")
        return None


# ================= CHANGE DETECTOR =================
def has_real_changes(target: Any) -> bool:
    try:
        state = inspect(target)
        for attr in state.attrs:
            if attr.history.has_changes():
                return True
        return False
    except Exception as e:
        logger.error(f"❌ Change detect error: {e}")
        return False


# ================= DEDUP HASH =================
def make_event_hash(table: str, pk: str, event_type: str, payload: Dict[str, Any]) -> str:
    """
    💡 Payload toza dict bo'lgani uchun uning deterministic (izchil) tartiblangan 
    string ko'rinishini hosil qilib keyin hashlash kerak (sort_keys=True shart).
    """
    serialized_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    raw = f"{table}:{pk}:{event_type}:{serialized_payload}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ================= PAYLOAD BUILDER =================
def build_payload(target: Any) -> Dict[str, Any]:
    """
    🚨 DOIM valid Python lug'atini (dict) qaytaradi, JSON/JSONB ustuniga moslashtirilgan.
    """
    try:
        data = {}

        for col in inspect(target).mapper.column_attrs:
            key = col.key
            val = getattr(target, key)

            # 🔥 Maxsus ma'lumot turlarini JSON-safe formatga o'giramiz
            if isinstance(val, datetime):
                data[key] = val.isoformat()
            elif isinstance(val, Decimal):
                data[key] = float(val)  # Yoki aniqlik yo'qolmasligi uchun str(val) qilish mumkin
            elif isinstance(val, UUID):
                data[key] = str(val)
            else:
                data[key] = val

        # 🔥 Agarda siqish (compression) yoqilgan bo'lsa, uni alohida meta-dict ichiga o'raymiz
        if ENABLE_COMPRESSION:
            raw_str = json.dumps(data, ensure_ascii=False)
            compressed_hex = zlib.compress(raw_str.encode(), level=6).hex()
            return {
                "is_compressed": True,
                "data": compressed_hex  # Worker (Consumer) buni ochganda zlib.decompress qiladi
            }

        return data  # Toza Python dict formati

    except Exception as e:
        logger.warning(f"⚠️ Payload build failed: {e}")
        return {"error": "serialization_failed", "details": str(e)}


# ================= CORE HANDLER (Sinxron Connection konteksti) =================
def on_model_change(event_type: str):
    def handler(mapper: Any, connection: Connection, target: Any):
        start = datetime.now()
        table = getattr(target, "__tablename__", "unknown")

        try:
            pk_val = get_pk_value(target)
            if not pk_val:
                return

            # Empty update (o'zgarishsiz o'zgartirishlar) bo'lsa vaqtni tejash uchun tashlab ketamiz
            if event_type == "update" and not has_real_changes(target):
                return

            payload_dict = build_payload(target)

            event_hash = None
            if ENABLE_DEDUP:
                event_hash = make_event_hash(table, pk_val, event_type, payload_dict)

            # 🚨 CRITICAL FIX: event_hash va values() dagi ma'lumotlar jadval ustunlariga xavfsiz map qilindi.
            # SQLAlchemy `payload`ga berilgan dict-ni o'zi drayver darajasida PostgreSQL JSONB tipiga o'giradi.
            stmt = OutboxEvent.__table__.insert().values(
                id=str(uuid4()),
                aggregate=table,
                aggregate_id=pk_val,
                event_type=event_type,
                payload=payload_dict,       # To'g'rilandi (Dict)
                event_hash=event_hash,     # 🔥 CRITICAL FIX: Olib tashlangan ustun qaytarildi (Deduplikatsiya uchun)
                processed=False,
                retry_count=0,
                created_at=datetime.now(timezone.utc)
            )

            # Tranzaksiya ichida sinxron ravishda execution bajariladi
            connection.execute(stmt)

            # Ishlash tezligi monitoringi (Performance log)
            duration = (datetime.now() - start).total_seconds() * 1000
            if duration > SLOW_EVENT_THRESHOLD_MS:
                logger.warning(
                    f"⚠️ SLOW OUTBOX EVENT: {table} -> [{event_type}] bajarilishi {duration:.2f}ms cho'zildi."
                )

        except Exception as e:
            # 🚨 TRANSACTION SAFETY: Outboxdagi xato asosiy biznes tranzaksiyani (masalan, foydalanuvchi start bosganda bazaga yozilishini)
            # HECH QACHON buzmasligi (rollback qildirmasligi) shart. Shuning uchun faqat log qilamiz.
            logger.error(
                f"❌ Outbox write failed [{event_type}] on table '{table}': {e}"
            )

    return handler


# ================= ATTACH LISTENERS =================
def attach_cache_listeners():
    """
    🚀 Modellar uchun insert, update, delete oqimlarini Outbox tizimiga ulash
    """
    try:
        count = 0
        for model in MODELS_TO_WATCH:
            event.listen(model, "after_insert", on_model_change("insert"))
            event.listen(model, "after_update", on_model_change("update"))
            event.listen(model, "after_delete", on_model_change("delete"))
            count += 1

        logger.info(f"🚀 [Outbox System] muvaffaqiyatli yuklandi: {count} ta model nazorat ostiga olindi.")

    except Exception as e:
        logger.critical(f"❌ [Outbox System] modellar tinglovchilarini ulashda kritik xato: {e}")