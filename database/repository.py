# database/repository.py
import logging
from typing import Optional, Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from database.models import DBUser
from aiogram.types import User as TgUser

logger = logging.getLogger("UserRepository")

class UserRepository:
    @staticmethod
    async def get_or_create(session: AsyncSession, tg_user: TgUser) -> DBUser:
        """
        Foydalanuvchini bazadan qidiradi, topilmasa yangi yaratadi.
        PostgreSQL 'ON CONFLICT' (Upsert) mexanizmidan foydalanadi.
        """
        try:
            # 1. Upsert statement tayyorlash
            stmt = insert(DBUser).values(
                user_id=tg_user.id,
                username=tg_user.username,
                status="user",
                points=0
            )

            # 2. Agar foydalanuvchi allaqachon bo'lsa, username'ni yangilab qo'yamiz
            # (Foydalanuvchi username'ini o'zgartirgan bo'lishi mumkin)
            stmt = stmt.on_conflict_do_update(
                index_elements=['user_id'],
                set_={
                    "username": tg_user.username
                }
            ).returning(DBUser)

            result = await session.execute(stmt)
            return result.scalar_one()

        except Exception as e:
            logger.error(f"Error in get_or_create: {e}")
            # Agar xato bo'lsa (masalan, DB o'chgan), SELECT qilib ko'ramiz
            query = select(DBUser).where(DBUser.user_id == tg_user.id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[DBUser]:
        """Foydalanuvchini ID bo'yicha olish."""
        stmt = select(DBUser).where(DBUser.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_points(session: AsyncSession, user_id: int, points: int):
        """Foydalanuvchi ballarini yangilash."""
        stmt = (
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(points=DBUser.points + points)
        )
        await session.execute(stmt)

    @staticmethod
    async def set_vip(session: AsyncSession, user_id: int, duration_days: int):
        """VIP statusini belgilash."""
        from datetime import datetime, timedelta
        expire_date = datetime.now() + timedelta(days=duration_days)
        
        stmt = (
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(status="vip", vip_expire_date=expire_date)
        )
        await session.execute(stmt)