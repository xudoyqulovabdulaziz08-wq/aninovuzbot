import logging
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, and_  
from database.models import DBUser
from database.cache import valkey

logger = logging.getLogger("UserRepository")


class UserRepository:

    # ================= GET OR CREATE (UPSERT) =================
    @staticmethod
    async def get_or_create(session: AsyncSession, tg_user) -> DBUser:
        """
        🔥 1 QUERY UPSERT
        🔥 RACE SAFE
        🔥 HIGH LOAD READY
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

            # 🔥 IMPORTANT: ensure fully loaded object
            try:
                await session.refresh(user)
            except Exception:
                pass

            return user

        except Exception as e:
            logger.error(f"❌ get_or_create error: {e}")

            # fallback
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

    # ================= CACHE INVALIDATION =================
    @staticmethod
    async def _invalidate_cache(user_id: int):
        """
        🔥 L1 + L2 cache cleanup
        """
        try:
            # L2 (Redis)
            if valkey.is_alive:
                await valkey.delete("users", user_id)

            # L1 (Orchestrator)
            try:
                from services.orchestrator import state
                state.l1_cache.pop(user_id, None)
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"cache invalidate error: {e}")

    # ================= UPDATE POINTS =================
    @staticmethod
    async def update_points(session: AsyncSession, user_id: int, points: int):
        """
        🔥 ATOMIC
        🔥 CACHE SAFE
        """

        try:
            result = await session.execute(
                update(DBUser)
                .where(DBUser.user_id == user_id)
                .values(points=DBUser.points + points)
            )

            if result.rowcount == 0:
                logger.warning(f"⚠️ update_points: user not found {user_id}")
                return

            # 🔥 CACHE CLEAR
            await UserRepository._invalidate_cache(user_id)

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
                return

            await UserRepository._invalidate_cache(user_id)

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
                return

            await UserRepository._invalidate_cache(user_id)

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
                return

            await UserRepository._invalidate_cache(user_id)

        except Exception as e:
            logger.error(f"❌ add_referral error: {e}")
            raise
    # ================= SET REFERRER =================
    @staticmethod
    async def set_referrer(session: AsyncSession, user_id: int, ref_id: int):
        """
        🔥 Yangi foydalanuvchiga taklif qilgan odamni biriktirish.
        """
        try:
            # Faqat referred_by bo'sh bo'lsagina yangilaymiz (takroriy referral oldini olish)
            stmt = (
                update(DBUser)
                .where(and_(DBUser.user_id == user_id, DBUser.referred_by.is_(None)))
                .values(referred_by=ref_id)
            )
            result = await session.execute(stmt)
            
            if result.rowcount > 0:
                await UserRepository._invalidate_cache(user_id)
                
        except Exception as e:
            logger.error(f"❌ set_referrer error: {e}")
            raise

    # ================= PROCESS REFERRAL REWARD =================
    @staticmethod
    async def process_referral_reward(session: AsyncSession, user_id: int, amount: int = 10) -> tuple[bool, Optional[int]]:
        """
        🔥 ATOMIC REWARD PROCESS
        1. Taklif qilingan foydalanuvchini tekshiradi.
        2. Taklifchiga (referrer) ball qo'shadi.
        3. Referred_by ni tozalaydi (bir marta ochko berish uchun).
        4. Keshni yangilaydi.
        """
        try:
            # 1. Foydalanuvchini va uning taklifchisini olish
            result = await session.execute(
                select(DBUser).where(DBUser.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user or not user.referred_by:
                return False, None

            ref_id = user.referred_by

            # 2. Taklif qilgan odamga ball qo'shish va hisoblagichni oshirish
            ref_update = await session.execute(
                update(DBUser)
                .where(DBUser.user_id == ref_id)
                .values(
                    points=DBUser.points + amount,
                    referral_count=DBUser.referral_count + 1
                )
            )

            if ref_update.rowcount == 0:
                return False, None

            # 3. Foydalanuvchidan taklifchini tozalash (qayta ball bermaslik uchun)
            user.referred_by = None
            
            # 4. Tranzaksiyani saqlash (Middleware commit qiladi, lekin biz keshni tozalashimiz kerak)
            await session.flush() 

            # 5. KESH TOZALASH (L1 + L2)
            await UserRepository._invalidate_cache(user_id) # O'zining referred_by o'zgardi
            await UserRepository._invalidate_cache(ref_id)  # Taklifchining ballari o'zgardi

            return True, ref_id

        except Exception as e:
            logger.error(f"❌ process_referral_reward error: {e}")
            return False, None