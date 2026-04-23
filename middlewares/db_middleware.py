import asyncio
import logging
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
                db_user = None
                cached_user = None

                # 1. KESHNI TEKSHIRISH (TIMEOUT BILAN)
                try:
                    # Agar Redis 1 soniyada javob bermasa, kutmaymiz
                    cached_user = await asyncio.wait_for(
                        valkey.get("users", user_obj.id), 
                        timeout=1.0
                    )
                except Exception as e:
                    logging.error(f"Redis error in middleware: {e}")

                if cached_user:
                    try:
                        db_user = DBUser(**cached_user)
                        
                        # SINXRONIZATSIYA: Faqat o'zgarish bo'lsa fonda yangilaymiz
                        if db_user.username != user_obj.username:
                            db_user.username = user_obj.username
                            await session.merge(db_user)
                            await session.commit()
                            # Keshni fonda yangilash (foydalanuvchini kutib o'tirmaydi)
                            asyncio.create_task(valkey.set(db_user))
                    except Exception as e:
                        logging.error(f"Error mapping cached user: {e}")
                        db_user = None # Xato bo'lsa bazadan qayta yuklaymiz

                # 2. AGAR KESHDA BO'LMASA YOKI XATO BO'LSA
                if not db_user:
                    try:
                        result = await session.execute(
                            select(DBUser).where(DBUser.user_id == user_obj.id)
                        )
                        db_user = result.scalar_one_or_none()

                        if not db_user:
                            # 3. YANGI USER YARATISH
                            db_user = DBUser(
                                user_id=user_obj.id,
                                username=user_obj.username,
                                status="user"
                            )
                            session.add(db_user)
                            await session.commit()
                            await session.refresh(db_user)
                        
                        # Keshga yozishni fonda bajaramiz
                        asyncio.create_task(valkey.set(db_user))
                    except Exception as e:
                        logging.error(f"Database error in middleware: {e}")
                        # Agar baza ham o'chgan bo'lsa, xatoni ko'rsatamiz
                        return await event.answer("⚠️ Ma'lumotlar bazasi bilan aloqa uzildi.")

                data["user"] = db_user

            return await handler(event, data)