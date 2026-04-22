from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import DBUser
from database.cache import valkey 

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool):
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with self.session_pool() as session:
            data["session"] = session
            data["valkey"] = valkey

            user: User = data.get("event_from_user")
            if user:
                # Keshdan foydalanuvchini olish
                cached_user = await valkey.get("users", user.id)

                if not cached_user:
                    # Bazadan qidirish
                    result = await session.execute(
                        select(DBUser).where(DBUser.user_id == user.id)
                    )
                    db_user = result.scalar_one_or_none()

                    if not db_user:
                        # Yangi user qo'shish
                        db_user = DBUser(
                            user_id=user.id,
                            username=user.username,
                            status="user"
                        )
                        session.add(db_user)
                        await session.commit()
                        await session.refresh(db_user)
                    
                    await valkey.set(db_user)
                    data["user"] = db_user
                else:
                    data["user"] = cached_user

            return await handler(event, data)
        