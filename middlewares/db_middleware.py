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
            user_obj: User = data.get("event_from_user")
        
            if user_obj:
                # 1. Keshdan qidiramiz
                cached_user = await valkey.get("users", user_obj.id)
                db_user = None

                if cached_user:
                    # Keshdan olingan dictni DBUser obyektiga aylantiramiz
                    db_user = DBUser(**cached_user)
                
                    # 🔄 SINXRONIZATSIYA: Username o'zgargan bo'lsa yangilaymiz
                    if db_user.username != user_obj.username:
                        db_user.username = user_obj.username
                        # Bazaga saqlaymiz (merge mavjud obyektni yangilaydi)
                        await session.merge(db_user)
                        await session.commit()
                        # Keshni ham yangilaymiz
                        await valkey.set(db_user)
                else:
                    # 2. Keshda bo'lmasa, Bazadan olamiz
                    result = await session.execute(
                        select(DBUser).where(DBUser.user_id == user_obj.id)
                    )
                    db_user = result.scalar_one_or_none()

                    if not db_user:
                        # 3. Yangi foydalanuvchi yaratish
                        db_user = DBUser(
                            user_id=user_obj.id,
                            username=user_obj.username,
                            status="user"
                        )
                        session.add(db_user)
                        await session.commit()
                        await session.refresh(db_user)
                
                    # Keshga yangi ma'lumotni yozamiz
                    await valkey.set(db_user)

                data["user"] = db_user

            return await handler(event, data)