import json
import logging

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from database.models import DBUser, Channel, List
from database.cache import valkey

logger = logging.getLogger("UserRepository")


class UserRepository:

    # ================= GET OR CREATE (UPSERT) =================
    @staticmethod
    async def get_or_create(session: AsyncSession, tg_user) -> DBUser:
        """
        🔥 1 QUERY UPSERT | RACE SAFE | HIGH LOAD READY
        """
        try:
            stmt = (
                insert(DBUser)
                .values(
                    user_id=tg_user.id,
                    username=tg_user.username,
                    status="user",
                    points=0,
                    referral_count=0
                    # ✅ is_vip olib tashlandi, chunki u modelda hybrid_property
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

            # 🔥 To'liq yuklangan obyektni kafolatlash
            try:
                await session.refresh(user)
            except Exception:
                pass

            return user

        except Exception as e:
            logger.error(f"❌ get_or_create error: {e}")

            # Fallback (Zaxira qidiruv)
            result = await session.execute(
                select(DBUser).where(DBUser.user_id == tg_user.id)
            )
            user = result.scalar_one_or_none()

            if not user:
                raise RuntimeError("CRITICAL: user not found after UPSERT fail")

            return user

    # ================= GET BY ID =================
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
            # L2 Cache (Valkey / Redis)
            if valkey.is_alive:
                await valkey.delete("users", user_id)

            # L1 Cache (Orchestrator Memory)
            try:
                from services.orchestrator import state
                state.l1_cache.pop(user_id, None)
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Cache invalidate error: {e}")

    # ================= UPDATE POINTS =================
    @staticmethod
    async def update_points(session: AsyncSession, user_id: int, points: int):
        """
        🔥 ATOMIC & CACHE SAFE
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
                    vip_expire_date=expire_date
                    # ✅ is_vip=True olib tashlandi (ustun emas)
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
                    vip_expire_date=None
                    # ✅ is_vip=False olib tashlandi (ustun emas)
                )
            )

            if result.rowcount == 0:
                logger.warning(f"⚠️ remove_vip: user not found {user_id}")
                return

            await UserRepository._invalidate_cache(user_id)

        except Exception as e:
            logger.error(f"❌ remove_vip error: {e}")
            raise

    # ================= ADD REFERRAL COUNT =================
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
        🔥 Yangi foydalanuvchiga taklif qilgan odamni xavfsiz biriktirish
        """
        try:
            # Faqat referred_by bo'sh bo'lsagina yangilaymiz (firbgarlikning oldini olish)
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
        """
        try:
            # 1. Foydalanuvchini olish
            result = await session.execute(
                select(DBUser).where(DBUser.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user or not user.referred_by:
                return False, None

            ref_id = user.referred_by

            # 2. Taklif qilganga ball qo'shish va takliflar sonini oshirish
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

            # 3. Qayta ball bermaslik uchun referred_by ni tozalash
            user.referred_by = None
            
            # 4. Tranzaksiyani flush qilish (ID larni sinxronlash va kesh tozalashga tayyorlash)
            await session.flush() 

            # 5. Keshlarni L1 va L2 darajasida tozalash
            await UserRepository._invalidate_cache(user_id)
            await UserRepository._invalidate_cache(ref_id)

            return True, ref_id

        except Exception as e:
            logger.error(f"❌ process_referral_reward error: {e}")
            return False, None
        






logger = logging.getLogger("ChannelRepository")

class ChannelRepository:

    @staticmethod
    async def get_all_channels(session: AsyncSession) -> List[Dict[str, Any]]:
        """
        🚀 Tizimdagi BARCHA kanallarni keshdan yoki bazadan olish (Toza dict formatida)
        """
        try:
            cached_data = await valkey.get(table="channels", obj_id="all_list")
            if cached_data and "list" in cached_data:
                return cached_data["list"]
        except Exception as cache_err:
            logger.warning(f"⚠️ get_all_channels kesh o'qishda xatolik: {cache_err}")

        # Keshda bo'lmasa bazadan yuklaymiz
        result = await session.execute(select(Channel).order_by(Channel.id.desc()))
        channels = result.scalars().all()

        channels_list = [
            {"id": ch.id, "channel_id": ch.channel_id, "title": ch.title, "url": ch.url, "is_active": ch.is_active}
            for ch in channels
        ]

        try:
            await valkey.set(table="channels", obj_id="all_list", data={"list": channels_list}, ttl=3600)
        except Exception as cache_err:
            logger.error(f"⚠️ get_all_channels keshga yozishda xatolik: {cache_err}")

        return channels_list

    @staticmethod
    async def get_all_active_channels(session: AsyncSession) -> List[Dict[str, Any]]:
        """
        🚀 Faqat FAOL kanallarni keshdan yoki bazadan olish.
        Middleware aynan shu metoddan toza lug'at (dict) oladi.
        """
        try:
            cached_data = await valkey.get(table="channels", obj_id="active_list")
            if cached_data and "list" in cached_data:
                return cached_data["list"]
        except Exception as cache_err:
            logger.warning(f"⚠️ get_all_active_channels kesh o'qishda xatolik: {cache_err}")

        # Keshda bo'lmasa, bazadan olamiz
        result = await session.execute(select(Channel).where(Channel.is_active == True))
        active_channels = result.scalars().all()

        active_list = [
            {"id": ch.id, "channel_id": ch.channel_id, "title": ch.title, "url": ch.url, "is_active": ch.is_active}
            for ch in active_channels
        ]

        try:
            await valkey.set(table="channels", obj_id="active_list", data={"list": active_list}, ttl=3600)
        except Exception as cache_err:
            logger.error(f"⚠️ get_all_active_channels keshga yozishda xatolik: {cache_err}")

        return active_list

    @staticmethod
    async def get_channel_by_id(session: AsyncSession, channel_id: int) -> Optional[Dict[str, Any]]:
        """
        🚀 Bitta kanalni ID bo'yicha keshdan yoki bazadan qidirish.
        Qaytariladigan qiymat: toza lug'at (dict) yoki None
        """
        obj_key = str(channel_id)
        try:
            cached_data = await valkey.get(table="channels", obj_id=obj_key)
            if cached_data:
                return cached_data
        except Exception as cache_err:
            logger.warning(f"⚠️ get_channel_by_id kesh o'qishda xatolik: {cache_err}")

        # Keshda bo'lmasa bazadan qidiramiz
        result = await session.execute(select(Channel).where(Channel.channel_id == channel_id))
        channel = result.scalar_one_or_none()

        if channel:
            channel_dict = {
                "id": channel.id, 
                "channel_id": channel.channel_id, 
                "title": channel.title, 
                "url": channel.url, 
                "is_active": channel.is_active
            }
            try:
                await valkey.set(table="channels", obj_id=obj_key, data=channel_dict, ttl=3600)
            except Exception as cache_err:
                logger.error(f"⚠️ get_channel_by_id keshga yozishda xatolik: {cache_err}")
                
            return channel_dict
            
        return None

    @staticmethod
    async def add_channel(session: AsyncSession, channel_id: int, title: str, url: str) -> Channel:
        """
        ➕ Yangi kanal qo'shish va universal keshlarni tozalash
        """
        try:
            channel = Channel(channel_id=channel_id, title=title, url=url, is_active=True)
            session.add(channel)
            await session.commit()
            
            # 🔥 TUZATILDI: Hammasi va Aktivlar ro'yxati keshlari tozalab tashlanadi
            await valkey.invalidate(table="channels", obj_id="all_list")
            await valkey.invalidate(table="channels", obj_id="active_list")
            return channel
        except Exception as e:
            await session.rollback()
            logger.error(f"add_channel error: {e}")
            raise e

    @staticmethod
    async def toggle_channel_status(session: AsyncSession, channel_id: int, is_active: bool):
        """
        🔄 Kanal holatini o'zgartirish va bog'liq barcha keshlarni tozalash
        """
        try:
            await session.execute(
                update(Channel).where(Channel.channel_id == channel_id).values(is_active=is_active)
            )
            await session.commit()
            
            # 🔥 TUZATILDI: Status o'zgarganda hamma kesh zanjiri buziladi va yangilanadi
            await valkey.invalidate(table="channels", obj_id=str(channel_id))
            await valkey.invalidate(table="channels", obj_id="all_list")
            await valkey.invalidate(table="channels", obj_id="active_list")
        except Exception as e:
            await session.rollback()
            logger.error(f"toggle_channel_status error: {e}")
            raise e

    @staticmethod
    async def delete_channel_by_id(session: AsyncSession, channel_id: int) -> bool:
        """
        🗑 Kanalni o'chirish va keshdan butunlay yo'q qilish
        """
        try:
            stmt = delete(Channel).where(Channel.channel_id == channel_id)
            result = await session.execute(stmt)
            
            if result.rowcount > 0:
                await session.commit()
                # 🔥 TUZATILDI: O'chirilganda barcha kesh tozalanishi shart!
                await valkey.invalidate(table="channels", obj_id=str(channel_id))
                await valkey.invalidate(table="channels", obj_id="all_list")
                await valkey.invalidate(table="channels", obj_id="active_list")
                return True
                
            await valkey.invalidate(table="channels", obj_id=str(channel_id))
            await valkey.invalidate(table="channels", obj_id="all_list")
            await valkey.invalidate(table="channels", obj_id="active_list")
            return False
        except Exception as e:
            await session.rollback()
            logger.error(f"delete_channel_by_id error: {e}")
            raise e