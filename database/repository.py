import logging
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from datetime import datetime, timedelta, timezone

from database.models import DBUser

logger = logging.getLogger("UserRepository")


class UserRepository:

    # ================= GET OR CREATE (UPSERT) =================
    @staticmethod
    async def get_or_create(session: AsyncSession, tg_user) -> DBUser:
        """
        🔥 ULTRA FAST:
        - 1 query (Postgres UPSERT)
        - race-safe
        - high-load optimized
        """

        try:
            stmt = (
                insert(DBUser)
                .values(
                    user_id=tg_user.id,
                    username=tg_user.username,
                    status="user",
                    points=0,
                    referral_count=0,
                    is_vip=False
                )
                .on_conflict_do_update(
                    index_elements=[DBUser.user_id],
                    set_={
                        "username": tg_user.username
                    }
                )
                .returning(DBUser)
            )

            result = await session.execute(stmt)
            user = result.scalar_one()

            return user

        except Exception as e:
            logger.error(f"❌ get_or_create error: {e}")

            # fallback (VERY RARE)
            result = await session.execute(
                select(DBUser).where(DBUser.user_id == tg_user.id)
            )
            user = result.scalar_one_or_none()

            if not user:
                raise RuntimeError("CRITICAL: user not found after UPSERT fail")

            return user

    # ================= GET =================
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[DBUser]:
        try:
            result = await session.execute(
                select(DBUser).where(DBUser.user_id == user_id)
            )
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"❌ get_by_id error: {e}")
            return None

    # ================= ATOMIC POINTS UPDATE =================
    @staticmethod
    async def update_points(session: AsyncSession, user_id: int, points: int):
        """
        🔥 SAFE:
        - SQL atomic increment
        - race condition yo‘q
        """

        try:
            result = await session.execute(
                update(DBUser)
                .where(DBUser.user_id == user_id)
                .values(points=DBUser.points + points)
            )

            if result.rowcount == 0:
                logger.warning(f"⚠️ update_points: user not found {user_id}")

        except Exception as e:
            logger.error(f"❌ update_points error: {e}")
            raise

    # ================= SET VIP =================
    @staticmethod
    async def set_vip(session: AsyncSession, user_id: int, days: int):
        try:
            expire_date = datetime.now(timezone.utc) + timedelta(days=days)

            result = await session.execute(
                update(DBUser)
                .where(DBUser.user_id == user_id)
                .values(
                    status="vip",
                    is_vip=True,
                    vip_expire_date=expire_date
                )
            )

            if result.rowcount == 0:
                logger.warning(f"⚠️ set_vip: user not found {user_id}")

        except Exception as e:
            logger.error(f"❌ set_vip error: {e}")
            raise

    # ================= REMOVE VIP =================
    @staticmethod
    async def remove_vip(session: AsyncSession, user_id: int):
        try:
            result = await session.execute(
                update(DBUser)
                .where(DBUser.user_id == user_id)
                .values(
                    status="user",
                    is_vip=False,
                    vip_expire_date=None
                )
            )

            if result.rowcount == 0:
                logger.warning(f"⚠️ remove_vip: user not found {user_id}")

        except Exception as e:
            logger.error(f"❌ remove_vip error: {e}")
            raise

    # ================= ADD REFERRAL =================
    @staticmethod
    async def add_referral(session: AsyncSession, user_id: int):
        try:
            result = await session.execute(
                update(DBUser)
                .where(DBUser.user_id == user_id)
                .values(referral_count=DBUser.referral_count + 1)
            )

            if result.rowcount == 0:
                logger.warning(f"⚠️ add_referral: user not found {user_id}")

        except Exception as e:
            logger.error(f"❌ add_referral error: {e}")
            raise