import json
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

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
        


class ChannelRepository:
    @staticmethod
    async def add_channel(session: AsyncSession, channel_id: int, title: str, url: str):
        """
        ➕ Yangi kanal qo'shish va barcha tegishli ro'yxat keshlarini 
        universal tarzda tozalash (Invalidation)
        """
        try:
            channel = Channel(channel_id=channel_id, title=title, url=url, is_active=True)
            session.add(channel)
            await session.commit()
            
            # 🔥 YANGILANDI: Eski metod o'rniga universal invalidate tizimi
            if hasattr(valkey, 'invalidate'):
                await valkey.invalidate(table="channels")
            elif hasattr(valkey, 'invalidate_channels'):
                # Zaxira varianti
                await valkey.invalidate_channels() 
            
            return channel
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Yangi kanal qo'shishda xatolik: {e}")
            raise e

    @staticmethod
    async def get_all_active_channels(session: AsyncSession) -> List[Channel]:
        """
        🚀 Keshlashtirilgan metod: Faol kanallarni Valkey'dan chaqmoq tezligida oladi
        """
        CACHE_KEY = "cache:active_channels"
        
        # 1. Avval Valkey keshidan tekshiramiz
        try:
            cached_data = await valkey.get(CACHE_KEY)
            if cached_data:
                # Keshda ma'lumot bo'lsa, uni tezda model obyektlariga o'girib qaytaramiz (~5-10 ms)
                channels_data = json.loads(cached_data)
                return [Channel(**ch) for ch in channels_data]
        except Exception as cache_err:
            logger.warning(f"Faol kanallar keshini o'qishda xatolik: {cache_err}")

        # 2. Keshda yo'q bo'lsa, bazadan (PostgreSQL/MySQL) qidiramiz
        result = await session.execute(select(Channel).where(Channel.is_active == True))
        active_channels = result.scalars().all()

        # 3. Keyingi safar bazaga qayta tushmasligi uchun keshga yozib qo'yamiz
        try:
            channels_dict = [
                {
                    "id": ch.id, 
                    "channel_id": ch.channel_id, 
                    "title": ch.title, 
                    "url": ch.url, 
                    "is_active": ch.is_active
                }
                for ch in active_channels
            ]
            # 1 soat (3600 soniya) davomida keshda saqlaymiz
            await valkey.set(CACHE_KEY, json.dumps(channels_dict), ex=3600)
        except Exception as cache_err:
            logger.error(f"Faol kanallarni keshga yozishda xatolik: {cache_err}")

        return active_channels
    

    @staticmethod
    async def get_channel_by_id(session: AsyncSession, channel_id: int):
        """
        🚀 Keshlashtirilgan metod: Kanal ma'lumotlarini ID bo'yicha keshdan yoki bazadan oladi
        """
        CACHE_KEY = f"cache:channel:{channel_id}"
        
        # 1. Avval Valkey keshidan qidiramiz
        try:
            cached_data = await valkey.get(CACHE_KEY)
            if cached_data:
                # Keshda bo'lsa, uni model obyektiga o'girib darhol qaytaramiz (~2-5 ms!)
                channel_data = json.loads(cached_data)
                return Channel(**channel_data)
        except Exception as cache_err:
            logger.warning(f"Kanal keshini ID bo'yicha o'qishda xatolik: {cache_err}")

        # 2. Keshda yo'q bo'lsa, bazadan (PostgreSQL/MySQL) qidiramiz
        result = await session.execute(select(Channel).where(Channel.channel_id == channel_id))
        channel = result.scalar_one_or_none()

        # 3. Agar kanal topilsa, keyingi safar tez ishlashi uchun keshga yozib qo'yamiz
        if channel:
            try:
                channel_dict = {
                    "id": channel.id, 
                    "channel_id": channel.channel_id, 
                    "title": channel.title, 
                    "url": channel.url, 
                    "is_active": channel.is_active
                }
                # 1 soat davomida keshda saqlaymiz
                await valkey.set(CACHE_KEY, json.dumps(channel_dict), ex=3600)
            except Exception as cache_err:
                logger.error(f"Kanalni keshga yozishda xatolik: {cache_err}")

        return channel
    
    async def toggle_channel_status(session: AsyncSession, channel_id: int, is_active: bool):
        """
        🔄 Kanal statusini o'zgartirish va barcha tegishli keshlar (L1/L2)
        hamda individual kanal keshini universal invalidate qilish
        """
        try:
            # 1. Bazada statusni yangilaymiz
            await session.execute(
                update(Channel).where(Channel.channel_id == channel_id).values(is_active=is_active)
            )
            await session.commit()
            
            # 2. 🔥 ESKI METOD O'RNIGA: Universal invalidate tizimini chaqiramiz
            # Bu bitta urinishda 'cache:all_channels', 'cache:active_channels' 
            # va 'cache:channel:{channel_id}' keshlarining hammasini tozalaydi!
            if hasattr(valkey, 'invalidate'):
                await valkey.invalidate(table="channels", obj_id=channel_id)
            elif hasattr(valkey, 'invalidate_channels'):
                # Agar mabodo CacheManager hali to'liq ulanmagan bo'lsa, eski usul zaxira sifatida
                await valkey.invalidate_channels()

        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Kanal statusini o'zgartirishda xatolik: {e}")
            raise e

    # 🔄 ESKI ALIAS O'ZGARTIRILDI: Endi u rostdan ham hamma kanallarni qaytaradi (Admin ko'rishi uchun)
    @staticmethod
    async def get_all_channels(session: AsyncSession) -> List[Channel]:
        """
        🚀 Keshlashtirilgan metod: Tizimdagi barcha faol va nofaol kanallarni
        Valkey keshidan chaqmoq tezligida oladi (~5-10 ms!)
        """
        CACHE_KEY = "cache:all_channels"
        
        # 1. Avval Valkey keshidan tekshiramiz
        try:
            cached_data = await valkey.get(CACHE_KEY)
            if cached_data:
                # Keshda ma'lumot bo'lsa, stringni JSON qilib, model obyektlariga o'giramiz
                channels_data = json.loads(cached_data)
                return [Channel(**ch) for ch in channels_data]
        except Exception as cache_err:
            logger.warning(f"Barcha kanallar keshini o'qishda xatolik: {cache_err}")

        # 2. Keshda yo'q bo'lsa (yoki xato bersa), bazadan (PostgreSQL/MySQL) qidiramiz
        result = await session.execute(select(Channel).order_by(Channel.id.desc()))
        channels = result.scalars().all()

        # 3. Keyingi safar bazaga qayta tushmasligi uchun keshga yozib qo'yamiz
        try:
            channels_dict = [
                {
                    "id": ch.id, 
                    "channel_id": ch.channel_id, 
                    "title": ch.title, 
                    "url": ch.url, 
                    "is_active": ch.is_active
                }
                for ch in channels
            ]
            # 1 soat (3600 soniya) davomida keshda saqlaymiz
            await valkey.set(CACHE_KEY, json.dumps(channels_dict), ex=3600)
        except Exception as cache_err:
            logger.error(f"Barcha kanallarni keshga yozishda xatolik: {cache_err}")

        return channels

    # 🗑 YANGI QO'SHILDI: Kanalni bazadan butunlay o'chirish metodi
    @staticmethod
    async def delete_channel_by_id(session: AsyncSession, channel_id: int) -> bool:
        """Kanalni bazadan butunlay o'chirish va keshni avtomatik tozalash"""
        try:
            stmt = delete(Channel).where(Channel.channel_id == channel_id)
            result = await session.execute(stmt)
        
            # Agar birorta qator o'chgan bo'lsa, rowcount 1 (yoki undan ko'p) bo'ladi
            if result.rowcount > 0:
                await session.commit()
            
                # 🔥 REPOSITORY ICHIDA KESHNI TOZALASH (TO'G'RILANDI):
                # Yangi universal 'invalidate' metodi borligini tekshiramiz
                if hasattr(valkey, 'invalidate'):
                    await valkey.invalidate(table="channels", obj_id=channel_id)
                elif hasattr(valkey, 'invalidate_channels'):
                    # Zaxira variant (agar eski metod hali o'chirilmagan bo'lsa)
                    await valkey.invalidate_channels()
                
                return True
            
            return False
        
        except Exception as e:
            await session.rollback()
            raise e
    