import logging
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection
from database.models import OutboxEvent, MODELS_TO_WATCH

logger = logging.getLogger("OutboxEmitter")

def get_pk_value(target):
    """Primary key qiymatini xavfsiz olish."""
    try:
        # inspect(target) o'rniga modelning mapperidan foydalanamiz
        mapper = inspect(target).mapper
        pk_values = [str(getattr(target, column.key)) for column in mapper.primary_key]
        return ":".join(pk_values)
    except Exception as e:
        logger.error(f"PK extraction failed for {target.__tablename__}: {e}")
        return None

def on_model_change(mapper, connection: Connection, target):
    """Event handler: O'zgarishlarni Outbox'ga yozadi."""
    pk_val = get_pk_value(target)
    if not pk_val:
        return

    try:
        # SQL expression construct orqali tezkor insert
        stmt = OutboxEvent.__table__.insert().values(
            id=str(uuid4()),
            aggregate=target.__tablename__,
            aggregate_id=pk_val,
            processed=False,
            created_at=datetime.now(timezone.utc)
        )
        connection.execute(stmt)
    except Exception as e:
        # Bu yerda loglash muhim, chunki bu xato asosiy tranzaksiyani to'xtatishi mumkin
        logger.error(f"Failed to write OutboxEvent for {target.__tablename__}: {e}")

def attach_cache_listeners():
    """Barcha kuzatiladigan modellarga listenerlarni ulaydi."""
    for model_class in MODELS_TO_WATCH:
        event.listen(model_class, "after_insert", on_model_change)
        event.listen(model_class, "after_update", on_model_change)
        event.listen(model_class, "after_delete", on_model_change)
    
    logger.info(f"✅ Outbox listeners attached to {len(MODELS_TO_WATCH)} models.")