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

            user_obj: User = data.get("event_from_user")
            if user_obj:
                # 1. Keshdan foydalanuvchini qidiramiz
                cached_user = await valkey.get("users", user_obj.id)

                if not cached_user:
                    # 2. Agar keshda bo'lmasa, Bazadan qidiramiz
                    result = await session.execute(
                        select(DBUser).where(DBUser.user_id == user_obj.id)
                    )
                    db_user = result.scalar_one_or_none()

                    if not db_user:
                        # 3. Agar bazada ham bo'lmasa - YANGI FOYDALANUVCHI
                        db_user = DBUser(
                            user_id=user_obj.id,
                            username=user_obj.username,
                            status="user"
                        )
                        session.add(db_user)
                        await session.commit()
                        await session.refresh(db_user)
                    
                    # 4. Keshga yozamiz (Model obyektini uzatamiz)
                    await valkey.set(db_user)
                    data["user"] = db_user
                else:
                    # 5. ✅ MANA SHU YERGA: 
                    # Keshdan kelgan dictni DBUser obyektiga aylantiramiz.
                    # Shunda handlerlarda user['status'] emas, user.status deb yozaverasiz.
                    data["user"] = DBUser(**cached_user)

            return await handler(event, data)