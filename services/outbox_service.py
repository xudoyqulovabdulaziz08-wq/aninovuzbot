import orjson
from database.models import OutboxEvent

async def create_event(session, aggregate, agg_id, event_type, payload: dict):
    event = OutboxEvent(
        aggregate=aggregate,
        aggregate_id=str(agg_id),
        event_type=event_type,
        payload=orjson.dumps(payload).decode()
    )

    session.add(event)
    await session.commit()