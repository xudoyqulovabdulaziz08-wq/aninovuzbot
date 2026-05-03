import orjson
from datetime import datetime, timezone
from database.models import OutboxEvent


async def create_event(
    session,
    aggregate: str,
    agg_id: str,
    event_type: str,
    payload: dict,
    commit: bool = False
):
    """
    Outbox event creator (FAST + BATCH SAFE)
    """

    try:
        event = OutboxEvent(
            aggregate=aggregate,
            aggregate_id=str(agg_id),
            event_type=event_type,
            payload=orjson.dumps(payload).decode(),
            created_at=datetime.now(timezone.utc),
            processed=False,
            retry_count=0
        )

        session.add(event)

        # 🔥 optional commit (batch mode uchun)
        if commit:
            await session.commit()

        return event

    except Exception as e:
        # NOTE: bu failure DB transactionga ta'sir qilishi mumkin
        raise RuntimeError(f"Outbox create failed: {e}")