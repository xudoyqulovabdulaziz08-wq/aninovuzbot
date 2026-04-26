import logging
import uuid
from sqlalchemy import event, inspect
from database.models import OutboxEvent, MODELS_TO_WATCH
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger("OutboxEmitter")

def get_pk_value(target):
    try:
        state = inspect(target)
        pk_values = [str(getattr(target, attr.key)) for attr in state.mapper.primary_key]
        return ":".join(pk_values)
    except Exception as e:
        logger.error(f"PK extraction failed: {e}")
        return None

def attach_cache_listeners():
    """Modellarda o'zgarish bo'lsa, Outbox jadvaliga belgi qo'yish."""
    
    for model_class in MODELS_TO_WATCH:
        @event.listens_for(model_class, "after_insert")
        @event.listens_for(model_class, "after_update")
        @event.listens_for(model_class, "after_delete")
        def on_model_change(mapper, connection, target):
            pk_val = get_pk_value(target)
            if not pk_val: return

            # Xabarni tranzaksiya ichida Outbox'ga yozamiz
            # SQLAlchemy connection'dan foydalanamiz (Session emas)
            connection.execute(
                OutboxEvent.__table__.insert().values(
                    id=str(uuid4()),
                    aggregate=target.__tablename__,
                    aggregate_id=pk_val,
                    processed=False,
                    created_at=datetime.now(timezone.utc)
                )
            )
    logger.info("✅ Outbox listeners attached successfully.")