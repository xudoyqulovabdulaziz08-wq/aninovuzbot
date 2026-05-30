import json
import logging
import asyncio

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, update, and_, delete, literal_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from database.models import DBUser, Channel, List, Anime, Episode, Genre, anime_genres  # Modellar yo'li

from database.cache import valkey

logger = logging.getLogger("UserRepository")


class UserRepository:

    # ================= UTILS & HELPERS =================
    @staticmethod
    def _get_real_session(session: Any) -> Any:
        """ Middleware'dan kelayotgan SafeSession proxy ichidan haqiqiy sessiyani xavfsiz ajratib olish """
        if hasattr(session, "_session"):
            return session._session
        return session

    @staticmethod
    async def _prepare_session(session: Any) -> Any:
        """ Sessiya tayyorligini ta'minlash va haqiqiy sessiyani qaytarish """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        return UserRepository._get_real_session(session)

    @staticmethod
    def _to_dict(user: DBUser) -> dict:
        """ SQLAlchemy modelini keshbop va xavfsiz dict holatiga keltirish """
        return {
            "user_id": user.user_id,
            "username": user.username,
            "status": user.status,
            "points": user.points,
            "referral_count": user.referral_count,
            "referred_by": user.referred_by,
            "vip_expire_date": user.vip_expire_date.isoformat() if user.vip_expire_date else None,
            "health_mode": user.health_mode,
            "joined_at": user.joined_at.isoformat() if user.joined_at else None
        }

    @staticmethod
    async def _invalidate_cache(user_id: int, broadcast: bool = True):
        """ 
        🔥 UNIVERSAL KESH TOZALASH 
        Kichik Muammo 3 FIX: broadcast boshqariladigan qilindi.
        Kichik Muammo 4 FIX: Jadval nomi 'users' ekanligi aniqlashtirildi.
        """
        try:
            await valkey.invalidate(table="users", obj_id=str(user_id), broadcast=broadcast)
        except Exception as e:
            logger.debug(f"❌ Cache invalidate error: {e}")

    # ================= GET OR CREATE (UPSERT) =================
    @staticmethod
    async def get_or_create(session: Any, tg_user: Any) -> dict:
        """
        🚀 Foydalanuvchini bazaga qo'shish yoki username o'zgargan bo'lsa yangilash (Upsert)
        Jiddiy Xato 4 FIX: Faqat xatolik aniq yuz bergandagina (xmax != 0) kesh tozalanadi.
        Qaytish qiymati doim DICT.
        """
        real_session = await UserRepository._prepare_session(session)

        # xmax != 0 sharti PostgreSQL-da satr yangilanganligini anglatadi (Yangi qo'shilsa xmax=0 bo'ladi)
        stmt = (
            insert(DBUser)
            .values(
                user_id=tg_user.id,
                username=tg_user.username,
                status="user",
                points=0,
                referral_count=0
            )
            .on_conflict_do_update(
                index_elements=[DBUser.user_id],
                set_={"username": tg_user.username}
            )
            .returning(DBUser, literal_column("xmax != 0").label("is_updated"))
        )
        
        result = await real_session.execute(stmt)
        row = result.fetchone()
        
        if not row:
            raise RuntimeError("❌ User upsert failed: No row returned.")
            
        user_model, is_updated = row[0], row[1]
        user_dict = UserRepository._to_dict(user_model)

        # Keshni faqat ma'lumot rostdan ham yangilangan bo'lsa tozalaymiz
        if is_updated:
            await UserRepository._invalidate_cache(tg_user.id, broadcast=True)
            
        return user_dict

    # ================= GET BY ID =================
    @staticmethod
    async def get_by_id(session: Any, user_id: int) -> Optional[dict]:
        """
        🔍 Foydalanuvchini L1/L2 keshdan yoki bazadan qidirish
        Jiddiy Xato 1 FIX: Har doim bir xil ma'lumot turi (dict) qaytaradi!
        """
        obj_key = str(user_id)
        
        # 1. Keshdan qidirish
        try:
            cached_user = await valkey.get(table="users", obj_id=obj_key)
            if cached_user and isinstance(cached_user, dict):
                return cached_user
        except Exception as cache_err:
            logger.warning(f"⚠️ get_by_id kesh o'qishda xatolik: {cache_err}")

        # 2. Agar keshda bo'lmasa, bazadan o'qish
        real_session = await UserRepository._prepare_session(session)

        try:
            result = await real_session.execute(
                select(DBUser).where(DBUser.user_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                user_dict = UserRepository._to_dict(user)
                try:
                    await valkey.set(table="users", obj_id=obj_key, data=user_dict, ttl=1800)
                except Exception as cache_err:
                    logger.error(f"⚠️ user keshga yozishda xato: {cache_err}")
                return user_dict
                
            return None
        except Exception as e:
            logger.error(f"❌ get_by_id error: {e}")
            raise

    # ================= UPDATE POINTS =================
    @staticmethod
    async def update_points(session: Any, user_id: int, points: int) -> bool:
        """
        🔥 ATOMIC POINTS UPDATE
        Jiddiy Xato 2 FIX: .commit() olib tashlandi, tranzaksiya boshqaruvi chaqiruvchida.
        """
        real_session = await UserRepository._prepare_session(session)

        result = await real_session.execute(
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(points=DBUser.points + points)
        )

        if result.rowcount == 0:
            logger.warning(f"⚠️ update_points: user not found {user_id}")
            return False

        await UserRepository._invalidate_cache(user_id, broadcast=True)
        return True

    # ================= SET VIP =================
    @staticmethod
    async def set_vip(session: Any, user_id: int, days: int) -> bool:
        """
        👑 Foydalanuvchiga VIP maqomini berish
        Jiddiy Xato 2 FIX: .commit() olib tashlandi.
        """
        real_session = await UserRepository._prepare_session(session)
        expire_date = datetime.now(timezone.utc) + timedelta(days=days)

        result = await real_session.execute(
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(
                status="vip",
                vip_expire_date=expire_date
            )
        )

        if result.rowcount == 0:
            logger.warning(f"⚠️ set_vip: user not found {user_id}")
            return False

        await UserRepository._invalidate_cache(user_id, broadcast=True)
        return True

    # ================= REMOVE VIP =================
    @staticmethod
    async def remove_vip(session: Any, user_id: int) -> bool:
        """
        📉 VIP maqomini olib tashlash
        Jiddiy Xato 2 FIX: .commit() olib tashlandi.
        """
        real_session = await UserRepository._prepare_session(session)

        result = await real_session.execute(
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(
                status="user",
                vip_expire_date=None
            )
        )

        if result.rowcount == 0:
            logger.warning(f"⚠️ remove_vip: user not found {user_id}")
            return False

        await UserRepository._invalidate_cache(user_id, broadcast=True)
        return True

    # ================= ADD REFERRAL COUNT =================
    @staticmethod
    async def add_referral(session: Any, user_id: int) -> bool:
        """
        ➕ Referallar sonini bittaga oshirish
        Jiddiy Xato 2 FIX: .commit() olib tashlandi.
        """
        real_session = await UserRepository._prepare_session(session)

        result = await real_session.execute(
            update(DBUser)
            .where(DBUser.user_id == user_id)
            .values(referral_count=DBUser.referral_count + 1)
        )

        if result.rowcount == 0:
            logger.warning(f"⚠️ add_referral: user not found {user_id}")
            return False

        await UserRepository._invalidate_cache(user_id, broadcast=True)
        return True

    # ================= SET REFERRER =================
    @staticmethod
    async def set_referrer(session: Any, user_id: int, ref_id: int) -> bool:
        """
        🔥 Yangi foydalanuvchiga taklif qilgan odamni xavfsiz biriktirish
        Kichik Muammo 2 FIX: Muvaffaqiyatsiz bo'lsa (masalan allaqachon biriktirilgan bo'lsa) debug log qo'shildi.
        """
        real_session = await UserRepository._prepare_session(session)

        stmt = (
            update(DBUser)
            .where(and_(DBUser.user_id == user_id, DBUser.referred_by.is_(None)))
            .values(referred_by=ref_id)
        )
        result = await real_session.execute(stmt)
        
        if result.rowcount > 0:
            await UserRepository._invalidate_cache(user_id, broadcast=True)
            return True
            
        logger.debug(f"ℹ️ set_referrer: Referrer already set or user not found for {user_id}")
        return False

    # ================= PROCESS REFERRAL REWARD =================
    @staticmethod
    async def process_referral_reward(session: Any, user_id: int, amount: int = 10) -> Tuple[bool, Optional[int]]:
        """
        🎁 Referal mukofotini berish va kesh zanjirlarini tozalash.
        Jiddiy Xato 2 FIX: .commit() va .rollback() olib tashlandi, bu ish handler zimmasida.
        Jiddiy Xato 3 FIX: Exception holatida xato yutib yuborilmaydi (raise qilinadi).
        """
        real_session = await UserRepository._prepare_session(session)

        try:
            # 1. Taklif qilingan foydalanuvchining referrer ID sini olish (Xavfsiz Race-condition oldini olish uchun FOR UPDATE bilan)
            stmt = select(DBUser.referred_by).where(DBUser.user_id == user_id).with_for_update()
            result = await real_session.execute(stmt)
            ref_id = result.scalar_one_or_none()

            if not ref_id:
                return False, None

            # 2. Taklif qilgan odamga ball va referal sonini atomik qo'shish
            ref_update = await real_session.execute(
                update(DBUser)
                .where(DBUser.user_id == ref_id)
                .values(
                    points=DBUser.points + amount,
                    referral_count=DBUser.referral_count + 1
                )
            )

            if ref_update.rowcount == 0:
                return False, None

            # 3. Ikkinchi marta ball olmasligi uchun referred_by ustunini tozalash
            await real_session.execute(
                update(DBUser).where(DBUser.user_id == user_id).values(referred_by=None)
            )
            
            # Keshni zanjirli tozalash
            await UserRepository._invalidate_cache(user_id, broadcast=True)
            await UserRepository._invalidate_cache(ref_id, broadcast=True)
            
            return True, ref_id

        except Exception as e:
            logger.error(f"❌ process_referral_reward error: {e}")
            raise  # Xato yuqoriga uzatiladi, tranzaksiyani boshqarayotgan tashqi kod o'zi rollback qiladi




logger = logging.getLogger("ChannelRepository")

class ChannelRepository:

    @staticmethod
    def _get_real_session(session: Any) -> Any:
        """ Middleware'dan kelayotgan SafeSession proxy ichidan haqiqiy sessiyani xavfsiz ajratib olish """
        if hasattr(session, "_session"):
            return session._session
        return session

    @staticmethod
    async def get_all_channels(session: Any) -> List[Dict[str, Any]]:
        """
        🚀 Tizimdagi BARCHA kanallarni keshdan (L1/L2) yoki bazadan olish (Toza dict formatida)
        """
        try:
            cached_data = await valkey.get(table="channels", obj_id="all_list")
            if cached_data and "list" in cached_data:
                return cached_data["list"]
        except Exception as cache_err:
            logger.warning(f"⚠️ get_all_channels kesh o'qishda xatolik: {cache_err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = ChannelRepository._get_real_session(session)

        # Keshda bo'lmasa bazadan yuklaymiz
        result = await real_session.execute(select(Channel).order_by(Channel.id.desc()))
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
    async def get_all_active_channels(session: Any) -> List[Dict[str, Any]]:
        """
        🚀 Faqat FAOL kanallarni keshdan yoki bazadan olish.
        Middleware / Filterlar aynan shu metoddan toza lug'at (dict) oladi.
        """
        try:
            cached_data = await valkey.get(table="channels", obj_id="active_list")
            if cached_data and "list" in cached_data:
                return cached_data["list"]
        except Exception as cache_err:
            logger.warning(f"⚠️ get_all_active_channels kesh o'qishda xatolik: {cache_err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = ChannelRepository._get_real_session(session)

        # Keshda bo'lmasa, bazadan olamiz
        result = await real_session.execute(select(Channel).where(Channel.is_active == True))
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
    async def get_channel_by_id(session: Any, channel_id: int) -> Optional[Dict[str, Any]]:
        """
        🚀 Bitta kanalni ID bo'yicha keshdan yoki bazadan qidirish.
        """
        obj_key = str(channel_id)
        try:
            cached_data = await valkey.get(table="channels", obj_id=obj_key)
            if cached_data:
                return cached_data
        except Exception as cache_err:
            logger.warning(f"⚠️ get_channel_by_id kesh o'qishda xatolik: {cache_err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = ChannelRepository._get_real_session(session)

        # Keshda bo'lmasa bazadan qidiramiz
        result = await real_session.execute(select(Channel).where(Channel.channel_id == channel_id))
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
    async def add_channel(session: Any, channel_id: int, title: str, url: str) -> Any:
        """
        ➕ Yangi kanal qo'shish va global klaster keshlarni sinxron tozalash
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = ChannelRepository._get_real_session(session)

        try:
            channel = Channel(channel_id=channel_id, title=title, url=url, is_active=True)
            real_session.add(channel)
            await real_session.commit()
            
            # 🔥 TUZATILDI: Yangi kanal qo'shilganda ro'yxatlar keshini barcha klaster node-larida urib tushiramiz
            await valkey.invalidate(table="channels", obj_id="all_list", broadcast=True)
            await valkey.invalidate(table="channels", obj_id="active_list", broadcast=True)
            return channel
        except Exception as e:
            await real_session.rollback()
            logger.error(f"❌ add_channel xatolik: {e}")
            raise e

    @staticmethod
    async def toggle_channel_status(session: Any, channel_id: int, is_active: bool):
        """
        🔄 Kanal holatini (Active/Inactive) o'zgartirish va bog'liq barcha keshlarni tozalash
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = ChannelRepository._get_real_session(session)

        try:
            await real_session.execute(
                update(Channel).where(Channel.channel_id == channel_id).values(is_active=is_active)
            )
            await real_session.commit()
            
            # 🔥 TUZATILDI: Status o'zgarganda klaster bo'ylab hamma kesh zanjiri invalidated bo'ladi
            await valkey.invalidate(table="channels", obj_id=str(channel_id), broadcast=True)
            await valkey.invalidate(table="channels", obj_id="all_list", broadcast=True)
            await valkey.invalidate(table="channels", obj_id="active_list", broadcast=True)
            logger.info(f"🧹 Kanal [{channel_id}] holati [{is_active}] ga o'zgardi, keshlar klaster bo'ylab tozalandi.")
        except Exception as e:
            await real_session.rollback()
            logger.error(f"❌ toggle_channel_status xatolik: {e}")
            raise e

    @staticmethod
    async def delete_channel_by_id(session: Any, channel_id: int) -> bool:
        """
        🗑 Kanalni o'chirish va keshdan butunlay yo'q qilish (Broadcast)
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = ChannelRepository._get_real_session(session)

        try:
            stmt = delete(Channel).where(Channel.channel_id == channel_id)
            result = await real_session.execute(stmt)
            
            if result.rowcount > 0:
                await real_session.commit()
                
                # 🔥 TUZATILDI: O'chirilganda L1 mahalliy va L2 distributed keshlar to'liq o'chirilishi shart!
                await valkey.invalidate(table="channels", obj_id=str(channel_id), broadcast=True)
                await valkey.invalidate(table="channels", obj_id="all_list", broadcast=True)
                await valkey.invalidate(table="channels", obj_id="active_list", broadcast=True)
                return True
                
            return False
        except Exception as e:
            await real_session.rollback()
            logger.error(f"❌ delete_channel_by_id xatolik: {e}")
            raise e
        










 

logger = logging.getLogger("AnimeRepository")

class AnimeRepository:

    @staticmethod
    def _get_real_session(session: Any) -> Any:
        """ Middleware'dan kelayotgan SafeSession proxy ichidan haqiqiy sessiyani xavfsiz ajratib olish """
        if hasattr(session, "_session"):
            return session._session
        return session

    @staticmethod
    async def add_anime(session: Any, title: str, poster_id: str, year: int, is_completed: bool, 
                        genres: List[str], description: str, languages: str, episodes: List[Dict[str, Any]]) -> Any:
        
        # 1. Sessiyani tayyorlash
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        try:
            # 2. Janrlarni olish yoki yaratish (Bitta optimallashgan so'rov)
            existing_res = await real_session.execute(select(Genre).where(Genre.name.in_(genres)))
            existing_genres = {g.name: g for g in existing_res.scalars().all()}
            
            anime_genres = []
            for g_name in genres:
                if g_name in existing_genres:
                    anime_genres.append(existing_genres[g_name])
                else:
                    new_genre = Genre(name=g_name)
                    anime_genres.append(new_genre)
            
            # 3. Anime obyektini yaratish
            anime = Anime(
                title=title, poster_id=poster_id, year=year, 
                is_completed=is_completed, description=description, 
                languages=languages, genres=anime_genres
            )
            
            real_session.add(anime)
            await real_session.commit()
            
            # 4. Refresh (N+1 muammosini selectinload bilan yechish)
            stmt = (select(Anime)
                    .options(selectinload(Anime.genres), selectinload(Anime.episodes))
                    .where(Anime.anime_id == anime.anime_id))
            result = await real_session.execute(stmt)
            
            # 🔥 Yangi anime qo'shilganda qidiruv xaritasiga klaster bo'ylab qo'shib qo'yamiz
            await valkey.update_single_anime_in_search_map(
                anime_id=anime.anime_id,
                title=anime.title,
                year=anime.year
            )
            
            return result.scalar_one()
            
        except Exception as e:
            await real_session.rollback()
            logger.error(f"❌ add_anime xatolik: {e}")
            raise e
        
    @staticmethod
    async def add_anime_episode(session: Any, anime_id: int, episode_num: int, file_id: str) -> Optional[Any]:
        """
        ➕ Yangi epizod qo'shish, joriy anime keshini va klaster L1 keshlarini xavfsiz tozalash
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        try:
            episode = Episode(anime_id=anime_id, episode=episode_num, file_id=file_id)
            real_session.add(episode)
            await real_session.commit()
            
            # 🔥 YANGI KESH MANTIQI INTEGRATSIYASI:
            # Standart anime keshini tozalaymiz (L1 local xotira + L2 distributed Redis hamma serverlarda o'chadi)
            await valkey.invalidate(table="anime_list", obj_id=f"id_{anime_id}", broadcast=True)
            
            # Epizod file_id-sini 3 kunga L1 va L2 keshga yozamiz
            await valkey.set_episode_file_id(
                anime_id=anime_id,
                episode=episode_num,
                file_id=file_id,
                ttl=86400 * 3
            )
            
            logger.info(f"✅ Anime [{anime_id}] ga {episode_num}-qism qo'shildi, kesh klaster bo'ylab sinxron tozalandi.")
            return episode
        except Exception as e:
            await real_session.rollback()
            logger.error(f"❌ add_anime_episode ichida xatolik: {e}")
            raise e
        
    @staticmethod
    async def update_anime(session: Any, anime_id: int, **kwargs) -> Optional[Any]:
        """
        🔄 Anime ma'lumotlarini yangilash, keshni tozalash va qidiruv xaritasini sinxronlash
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        try:
            stmt = update(Anime).where(Anime.anime_id == anime_id).values(**kwargs).returning(Anime)
            result = await real_session.execute(stmt)
            updated_anime = result.scalar_one_or_none()
            await real_session.commit()
            
            if updated_anime:
                # 1. Anime ma'lumotlari keshini barcha klaster node-larida tozalaymiz
                await valkey.invalidate(table="anime_list", obj_id=f"id_{anime_id}", broadcast=True)
                
                # 2. Agar sarlavha yoki yil o'zgargan bo'lsa, global qidiruv xaritasini yangilaymiz
                if "title" in kwargs or "year" in kwargs:
                    await valkey.update_single_anime_in_search_map(
                        anime_id=updated_anime.anime_id,
                        title=updated_anime.title,
                        year=updated_anime.year
                    )
                logger.info(f"🧹 Anime [{anime_id}] keshlari universal tarzda yangilandi.")
                
            return updated_anime
        except Exception as e:
            await real_session.rollback()
            logger.error(f"❌ update_anime ichida xatolik: {e}")
            raise e

    @staticmethod
    async def warm_up_anime_search_cache(session: AsyncSession):
        """ 🚀 Bot ishga tushganda yoki kesh batamom o'chganda qidiruv keshini to'ldirish """
        try:
            # Diqqat: Bu metodga faqat sof mustaqil AsyncSession (yoki pool sessiyasi) berilishi kerak
            stmt = select(Anime.anime_id, Anime.title, Anime.year)
            result = await session.execute(stmt)
            animes = result.all()

            if not animes:
                return

            cache_data = {str(a.anime_id): f"{a.title} ({a.year})" for a in animes}
            await valkey.set_anime_search_map(cache_data)
            logger.info("🚀 Anime qidiruv xaritasi (Warm-up) klaster tarmog'iga muvaffaqiyatli tarqatildi.")
        except Exception as e:
            logger.error(f"❌ Keshni warm-up qilishda xato: {e}")

    @staticmethod
    async def get_anime_by_id(session: Any, anime_id: int) -> Optional[Dict[str, Any]]:
        """ 🔍 Dual-Layer (L1 local + L2 Valkey) kesh orqali tezkor yuklash """
        obj_key = f"id_{anime_id}"
        try:
            # Yangi kesh menejeri L1 hit bo'lsa ma'lumot nusxasini (copy) xavfsiz qaytaradi
            cached = await valkey.get(table="anime_list", obj_id=obj_key)
            if cached:
                return cached
        except Exception as err:
            logger.warning(f"⚠️ Anime kesh o'qishda xato: {err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        # Kesh miss bo'lganda bazadan SelectInLoad bilan munosabatlarni yuklaymiz
        stmt = (
            select(Anime)
            .where(Anime.anime_id == anime_id)
            .options(selectinload(Anime.genres), selectinload(Anime.episodes))
        )
        result = await real_session.execute(stmt)
        anime = result.scalar_one_or_none()

        if anime:
            anime_dict = AnimeRepository._serialize_anime(anime)
            try:
                # L2 (Valkey) ga yozadi, u yerdan mahalliy L1 keshga ham o'tadi
                await valkey.set(table="anime_list", obj_id=obj_key, data=anime_dict, ttl=3600)
            except Exception as cache_err:
                logger.error(f"⚠️ Anime keshga yozishda xato: {cache_err}")
            return anime_dict
        return None

    @staticmethod
    async def search_anime_by_title(session: Any, query_text: str) -> List[Dict[str, Any]]:
        """ 🔎 Nom bo'yicha qidiruv: Oldin L1/L2 xaritadan qidiradi, topilmasa DB Fallback """
        query_text = query_text.lower().strip()
        matched_anime_ids = []

        try:
            # Yangi get_anime_search_map() 0-1ms ichida L1 local xotiradan qaytadi
            all_titles = await valkey.get_anime_search_map()
            if all_titles:
                for anime_id_str, full_title in all_titles.items():
                    if query_text in full_title.lower():
                        matched_anime_ids.append(int(anime_id_str))
                        if len(matched_anime_ids) >= 15:
                            break
        except Exception as cache_err:
            logger.error(f"⚠️ Qidiruv keshini o'qishda xatolik: {cache_err}")

        # Agar kesh xaritasidan IDlar topilsa, ularni parallel tarzda Dual-Layer keshdan yig'amiz
        if matched_anime_ids:
            tasks = [AnimeRepository.get_anime_by_id(session, a_id) for a_id in matched_anime_ids]
            fetched_animes = await asyncio.gather(*tasks)
            return [anime for anime in fetched_animes if anime]

        # FALLBACK: Agar kesh butkul bo'sh bo'lsa yoki topilmasa bazadan qidirish
        logger.warning(f"⚠️ Keshda moslik topilmadi. DB Fallback ishga tushdi: '{query_text}'")
        
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        stmt = (
            select(Anime)
            .where(Anime.title.ilike(f"%{query_text}%"))
            .options(selectinload(Anime.genres), selectinload(Anime.episodes))
            .limit(15)
        )
        result = await real_session.execute(stmt)
        animes = result.scalars().all()
        
        # 💡 DIQQAT: Sessiya yopilib ketib xato bermasligi uchun, qidiruv xaritasini kesh to'lgan sari
        # individual yangilab borish mantiqi yuqoridagi add/update ichiga joylandi.
        # Agar bu yerda global warm_up kerak bo'lsa, loyihadagi mustaqil session_factory dan foydalaning.

        return [AnimeRepository._serialize_anime(anime) for anime in animes]

    @staticmethod
    async def get_episode_file(session: Any, episode_num: int, anime_id: int) -> Optional[str]:
        """ 🎬 Epizod Telegram file_id-sini L1/L2 kesh zanjiridan super-tezkor olish """
        try:
            cached_file_id = await valkey.get_episode_file_id(anime_id, episode_num)
            if cached_file_id:
                return cached_file_id
        except Exception as err:
            logger.warning(f"⚠️ Epizod keshini o'qishda xato: {err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        stmt = select(Episode).where(Episode.anime_id == anime_id, Episode.episode == episode_num)
        result = await real_session.execute(stmt)
        ep = result.scalar_one_or_none()

        if ep:
            try:
                await valkey.set_episode_file_id(anime_id, episode_num, ep.file_id, ttl=86400 * 2)
            except Exception:
                pass
            return ep.file_id
        return None

    @staticmethod
    async def list_anime(session: Any) -> List[Any]:
        """ 📋 Bazadagi barcha animelarni oxirgi qo'shilgan tartibda olish (Proxy-safe) """
        if session is None:
            logger.error("❌ list_anime: session obyekti umuman berilmagan yoki None!")
            return []

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        real_session = AnimeRepository._get_real_session(session)

        if real_session is None:
            logger.error("❌ list_anime: Haqiqiy DB sessiyasini ochib bo'lmadi.")
            return []

        try:
            stmt = (
                select(Anime)
                .options(selectinload(Anime.genres))
                .order_by(Anime.anime_id.desc())
            )
            result = await real_session.execute(stmt)
            return result.scalars().all()
            
        except Exception as e:
            logger.error(f"❌ list_anime ichida xatolik yuz berdi: {e}")
            return []

    @staticmethod
    def _serialize_anime(anime: Any) -> Dict[str, Any]:
        """ 🔄 SQLAlchemy modelini xavfsiz JSON/Dict formatiga o'tkazish (N+1 safe) """
        return {
            "anime_id": anime.anime_id,
            "title": anime.title,
            "poster_id": anime.poster_id,
            "year": anime.year,
            "description": anime.description,
            "languages": anime.languages, 
            "is_completed": anime.is_completed,
            "views_week": anime.views_week,
            "genres": [g.name for g in anime.genres] if anime.genres else [],
            "episodes": [
                {"episode": ep.episode, "file_id": ep.file_id} 
                for ep in anime.episodes
            ] if anime.episodes else []
        }
    