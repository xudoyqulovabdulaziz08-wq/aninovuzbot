import asyncio
import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Union
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import select
from database.models import DBUser
from database.cache import valkey 

logger = logging.getLogger("DbMiddleware")

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
                # ❗ 10/10 PROTECTION: Resolving user with absolute fallback
                db_user = await self._resolve_user(session, user_obj)
                data["user"] = db_user or self._get_emergency_user(user_obj)

            return await handler(event, data)

    def _get_emergency_user(self, user_obj: User) -> SimpleNamespace:
        """
        ❗ 10/10 LIGHTWEIGHT FALLBACK: 
        ORM obyekt emas, balki xavfsiz SimpleNamespace qaytaramiz.
        Bu sessiya bilan konflikt yaratmaydi va xotiradan yutadi.
        """
        return SimpleNamespace(
            user_id=user_obj.id,
            username=user_obj.username,
            status="user",
            is_emergency=True # Handlerlarda tekshirish uchun bayroq
        )

    async def _resolve_user(self, session, user_obj: User) -> Union[DBUser, None]:
        """Userni kesh yoki bazadan aniqlash logikasi."""
        
        # 1. KESHNI TEKSHIRISH (v1 namespace bilan)
        cached_data = await valkey.get("db_users", user_obj.id)

        if cached_data:
            try:
                # ORM Mapping protection
                allowed_columns = DBUser.__table__.columns.keys()
                filtered_data = {k: v for k, v in cached_data.items() if k in allowed_columns}
                
                db_user = DBUser(**filtered_data)
                
                # Username sync logic
                if db_user.username != user_obj.username:
                    db_user.username = user_obj.username
                    merged_user = await session.merge(db_user)
                    await session.commit()
                    asyncio.create_task(valkey.set_model(merged_user))
                    return merged_user
                
                return db_user
            except Exception as e:
                logger.error(f"Cache mapping failed for {user_obj.id}: {e}")

        # 2. DB FALLBACK
        try:
            result = await session.execute(
                select(DBUser).where(DBUser.user_id == user_obj.id)
            )
            db_user = result.scalar_one_or_none()

            # 3. DB CREATE (Agar yangi foydalanuvchi bo'lsa)
            if not db_user:
                db_user = DBUser(
                    user_id=user_obj.id,
                    username=user_obj.username,
                    status="user"
                )
                session.add(db_user)
                await session.commit()
                await session.refresh(db_user)
            
            # Non-blocking cache update
            asyncio.create_task(valkey.set_model(db_user))
            return db_user

        except Exception as e:
            logger.critical(f"DATABASE CRITICAL FAILURE: {e}")
            return None # Emergency user __call__ ichida ishga tushadi