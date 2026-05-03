import logging
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from datetime import datetime, timedelta, timezone

from database.models import DBUser
from aiogram.types import User as TgUser

logger = logging.getLogger("UserRepository")


class UserRepository:

    # ================= GET OR CREATE =================
    @staticmethod
    async def get_or_create(session: AsyncSession, tg_user: TgUser) -> DBUser:
        """
        🔥 Optimized strategy:
        - SELECT first (fast)
        - INSERT only if needed
        - Object-level update (event-safe)
        """

        # ---------- FAST SELECT ----------
        result = await session.execute(
            select(DBUser).where(DBUser.user_id == tg_user.id)
        )
        user = result.scalar_one_or_none()

        if user:
            # ---------- SAFE UPDATE (ORM LEVEL) ----------
            if user.username != tg_user.username:
                try:
                    user.username = tg_user.username
                    session.add(user)  # 🔥 event trigger uchun
                except Exception as e:
                    logger.warning(f"Username update failed: {e}")

            return user

        # ---------- INSERT ----------
        try:
            stmt = insert(DBUser).values(
                user_id=tg_user.id,
                username=tg_user.username,
                status="user",
                points=0
            ).returning(DBUser)

            result = await session.execute(stmt)
            return result.scalar_one()

        except Exception as e:
            # ---------- RACE CONDITION ----------
            logger.warning(f"Insert race fallback: {e}")

            result = await session.execute(
                select(DBUser).where(DBUser.user_id == tg_user.id)
            )
            return result.scalar_one()


    # ================= GET =================
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[DBUser]:
        result = await session.execute(
            select(DBUser).where(DBUser.user_id == user_id)
        )
        return result.scalar_one_or_none()


    # ================= UPDATE POINTS =================
    @staticmethod
    async def update_points(session: AsyncSession, user_id: int, points: int):
        """
        🔥 Hybrid strategy:
        - Agar session ichida user bor bo‘lsa → ORM update
        - Aks holda → SQL update
        """

        # ORM cache check
        user = await session.get(DBUser, user_id)

        if user:
            user.points += points
            session.add(user)  # 🔥 event trigger
            return

        # fallback (fast SQL)
        await session.execute(
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(points=DBUser.points + points)
        )


    # ================= VIP =================
    @staticmethod
    async def set_vip(session: AsyncSession, user_id: int, duration_days: int):

        expire_date = datetime.now(timezone.utc) + timedelta(days=duration_days)

        user = await session.get(DBUser, user_id)

        if user:
            user.status = "vip"
            user.vip_expire_date = expire_date
            session.add(user)
            return

        await session.execute(
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(
                status="vip",
                vip_expire_date=expire_date
            )
        )