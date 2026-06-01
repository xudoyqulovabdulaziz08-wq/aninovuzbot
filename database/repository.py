import json
import logging
import asyncio

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, update, and_, delete, literal_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

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

    # ================= UTILS, HELPERS & DECORATOR LOGIC =================
    @staticmethod
    def _get_real_session(session: Any) -> Any:
        """ Middleware'dan kelayotgan SafeSession proxy ichidan haqiqiy sessiyani ajratib olish """
        if hasattr(session, "_session"):
            return session._session
        return session

    @staticmethod
    async def _prepare_session(session: Any) -> Any:
        """ 
        Sessiya tayyorlash va xavfsiz proxy ajratish mantiqini yagona helperga yig'ish.
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        return ChannelRepository._get_real_session(session)

    @staticmethod
    def _to_dict(channel: Channel) -> Dict[str, Any]:
        """ SQLAlchemy modelini keshbop va tizim uchun standart toza dict formatiga o'tkazish """
        return {
            "id": channel.id,
            "channel_id": channel.channel_id,
            "title": channel.title,
            "url": channel.url,
            "is_active": channel.is_active
        }

   # ====================================================================
    # 🧹 KESHNI KLASTER BO'YLAB TOZALASH (BROADCAST FIX)
    # ====================================================================
    @staticmethod
    async def _invalidate_channel_caches(channel_id: Optional[int] = None):
        """ 
        🚀 ASOSIY FIX: Endi to'g'ridan-to'g'ri valkey.invalidate chaqiriladi.
        Bu barcha serverlar (workerlar) dagi L1 lokal keshlarni sinxron tozalash 
        uchun avtomatik ravishda XADD (broadcast) stream xabarini yuboradi!
        """
        try:
            o_id = str(channel_id) if channel_id else None
            # broadcast=True parametri barcha workerlar xotirasini tozalashni kafolatlaydi
            await valkey.invalidate(table="channels", obj_id=o_id, broadcast=True)
            logger.info(f"🧹 Kanal keshlari butun klaster bo'ylab tozalandi. (ID: {o_id})")
        except Exception as e:
            logger.error(f"❌ _invalidate_channel_caches xatolik: {e}")

    # ================= GET ALL CHANNELS =================
    @staticmethod
    async def get_all_channels(session: Any) -> List[Dict[str, Any]]:
        """
        🚀 Tizimdagi BARCHA kanallarni keshdan yoki bazadan olish.
        """
        # 1. Keshdan tekshirish
        try:
            cached_data = await valkey.get(table="channels", obj_id="all_list")
            if cached_data is not None and isinstance(cached_data, list):
                return cached_data
        except Exception as cache_err:
            logger.warning(f"⚠️ get_all_channels kesh o'qishda xatolik: {cache_err}")

        # 🔥 CRITICAL FIX: Redis o'chiq bo'lsa, cheksiz siklga tushmaslik uchun Fallback
        if not valkey.is_alive or not valkey.redis:
            real_session = await ChannelRepository._prepare_session(session)
            result = await real_session.execute(select(Channel).order_by(Channel.id.desc()))
            return [ChannelRepository._to_dict(ch) for ch in result.scalars().all()]

        # 2. Singleflight / Cache Stampede Himoyasi (Distributed Redis Lock)
        lock_key = "channels:loading:all_list"
        if await valkey.redis.set(lock_key, "1", nx=True, ex=5):
            try:
                real_session = await ChannelRepository._prepare_session(session)
                result = await real_session.execute(select(Channel).order_by(Channel.id.desc()))
                channels_list = [ChannelRepository._to_dict(ch) for ch in result.scalars().all()]

                try:
                    await valkey.set(table="channels", obj_id="all_list", data=channels_list, ttl=3600)
                except Exception as cache_err:
                    logger.error(f"⚠️ get_all_channels keshga yozishda xatolik: {cache_err}")

                return channels_list
            finally:
                await valkey.redis.delete(lock_key)
        else:
            await asyncio.sleep(0.1)
            return await ChannelRepository.get_all_channels(session)

    # ================= GET ALL ACTIVE CHANNELS =================
    @staticmethod
    async def get_all_active_channels(session: Any) -> List[Dict[str, Any]]:
        """
        🚀 Faqat FAOL kanallarni keshdan yoki bazadan olish.
        """
        try:
            cached_data = await valkey.get(table="channels", obj_id="active_list")
            if cached_data is not None and isinstance(cached_data, list):
                return cached_data
        except Exception as cache_err:
            logger.warning(f"⚠️ get_all_active_channels kesh o'qishda xatolik: {cache_err}")

        # 🔥 CRITICAL FIX: Redis o'chiq bo'lsa, cheksiz siklga tushmaslik uchun Fallback
        if not valkey.is_alive or not valkey.redis:
            real_session = await ChannelRepository._prepare_session(session)
            result = await real_session.execute(select(Channel).where(Channel.is_active == True))
            return [ChannelRepository._to_dict(ch) for ch in result.scalars().all()]

        lock_key = "channels:loading:active_list"
        if await valkey.redis.set(lock_key, "1", nx=True, ex=5):
            try:
                real_session = await ChannelRepository._prepare_session(session)
                result = await real_session.execute(select(Channel).where(Channel.is_active == True))
                active_list = [ChannelRepository._to_dict(ch) for ch in result.scalars().all()]

                try:
                    await valkey.set(table="channels", obj_id="active_list", data=active_list, ttl=3600)
                except Exception as cache_err:
                    logger.error(f"⚠️ get_all_active_channels keshga yozishda xatolik: {cache_err}")

                return active_list
            finally:
                await valkey.redis.delete(lock_key)
        else:
            await asyncio.sleep(0.1)
            return await ChannelRepository.get_all_active_channels(session)

    # ================= GET CHANNEL BY ID =================
    @staticmethod
    async def get_channel_by_id(session: Any, channel_id: int) -> Optional[Dict[str, Any]]:
        """
        🚀 Bitta kanalni ID bo'yicha keshdan (L1/L2) yoki bazadan xavfsiz qidirish.
        """
        obj_key = str(channel_id)
        try:
            cached_data = await valkey.get(table="channels", obj_id=obj_key)
            if cached_data:
                return cached_data
        except Exception as cache_err:
            logger.warning(f"⚠️ get_channel_by_id kesh o'qishda xatolik: {cache_err}")

        real_session = await ChannelRepository._prepare_session(session)

        try:
            result = await real_session.execute(select(Channel).where(Channel.channel_id == channel_id))
            channel = result.scalar_one_or_none()

            if channel:
                channel_dict = ChannelRepository._to_dict(channel)
                try:
                    if valkey.is_alive:
                        await valkey.set(table="channels", obj_id=obj_key, data=channel_dict, ttl=3600)
                except Exception as cache_err:
                    logger.error(f"⚠️ get_channel_by_id keshga yozishda xatolik: {cache_err}")
                    
                return channel_dict
                
            return None
        except Exception as e:
            logger.error(f"❌ get_channel_by_id xatolik: {e}")
            raise

    # ================= ADD CHANNEL =================
    @staticmethod
    async def add_channel(session: Any, channel_id: int, title: str, url: str) -> Dict[str, Any]:
        real_session = await ChannelRepository._prepare_session(session)

        try:
            channel = Channel(channel_id=channel_id, title=title, url=url, is_active=True)
            real_session.add(channel)
            await real_session.flush()
            
            channel_dict = ChannelRepository._to_dict(channel)
            
            # 🔥 FIX: Kesh tozalash commitdan so'ng (Lambda lock bilan)
            if hasattr(session, "on_commit"):
                session.on_commit(lambda: ChannelRepository._invalidate_channel_caches())
            else:
                await ChannelRepository._invalidate_channel_caches()
                
            return channel_dict

        except IntegrityError as ie:
            logger.warning(f"⚠️ Channel {channel_id} allaqachon mavjud: {ie}")
            raise ValueError(f"Channel with ID {channel_id} already exists.")
        except Exception as e:
            logger.error(f"❌ add_channel kutilmagan xatolik: {e}")
            raise
    
    # ================= TOGGLE CHANNEL STATUS =================
    @staticmethod
    async def toggle_channel_status(session: Any, channel_id: int, is_active: bool) -> bool:
        real_session = await ChannelRepository._prepare_session(session)

        try:
            result = await real_session.execute(
                update(Channel)
                .where(Channel.channel_id == channel_id)
                .values(is_active=is_active)
            )
            
            if result.rowcount == 0:
                logger.warning(f"⚠️ toggle_channel_status: Kanal topilmadi [{channel_id}]")
                return False
            
            # 🔥 FIX: Lambda lock yordamida channel_id xavfsiz o'tkaziladi
            if hasattr(session, "on_commit"):
                session.on_commit(lambda cid=channel_id: ChannelRepository._invalidate_channel_caches(channel_id=cid))
            else:
                await ChannelRepository._invalidate_channel_caches(channel_id=channel_id)
                
            return True
        except Exception as e:
            logger.error(f"❌ toggle_channel_status xatolik: {e}")
            raise

    # ================= DELETE CHANNEL BY ID =================
    @staticmethod
    async def delete_channel_by_id(session: Any, channel_id: int) -> bool:
        real_session = await ChannelRepository._prepare_session(session)

        try:
            result = await real_session.execute(
                delete(Channel).where(Channel.channel_id == channel_id)
            )
            
            if result.rowcount > 0:
                # 🔥 FIX: Lambda lock bilan commit yakunlanishini kutish
                if hasattr(session, "on_commit"):
                    session.on_commit(lambda cid=channel_id: ChannelRepository._invalidate_channel_caches(channel_id=cid))
                else:
                    await ChannelRepository._invalidate_channel_caches(channel_id=channel_id)
                return True
                
            return False
        except Exception as e:
            logger.error(f"❌ delete_channel_by_id xatolik: {e}")
            raise










 

logger = logging.getLogger("AnimeRepository")

class AnimeRepository:

    # ================= UTILS, HELPERS & DECORATOR LOGIC =================
    @staticmethod
    def _get_real_session(session: Any) -> Any:
        """ Middleware'dan kelayotgan SafeSession proxy ichidan haqiqiy sessiyani xavfsiz ajratib olish """
        if hasattr(session, "_session"):
            return session._session
        return session

    @staticmethod
    async def _prepare_session(session: Any) -> Any:
        """ 
        Barcha metodlar uchun takrorlanuvchi sessiya tayyorlash logikasi.
        """
        if hasattr(session, "_ensure_session"):
            await session._ensure_session()
        return AnimeRepository._get_real_session(session)

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

    # ================= ADD ANIME =================
    @staticmethod
    async def add_anime(session: Any, title: str, poster_id: str, year: int, is_completed: bool, 
                        genres: List[str], description: str, languages: str, episodes: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        ➕ Yangi anime qo'shish va qidiruv xaritasini klaster bo'ylab yangilash
        JIDDIY FIX: commit() va rollback() olib tashlandi, natija model emas Dict shaklida qaytadi
        """
        real_session = await AnimeRepository._prepare_session(session)

        try:
            # 1. Janrlarni olish yoki yaratish
            existing_res = await real_session.execute(select(Genre).where(Genre.name.in_(genres)))
            existing_genres = {g.name: g for g in existing_res.scalars().all()}
            
            anime_genres = []
            for g_name in genres:
                if g_name in existing_genres:
                    anime_genres.append(existing_genres[g_name])
                else:
                    new_genre = Genre(name=g_name)
                    anime_genres.append(new_genre)
            
            # 2. Anime obyektini yaratish
            anime = Anime(
                title=title, poster_id=poster_id, year=year, 
                is_completed=is_completed, description=description, 
                languages=languages, genres=anime_genres
            )
            
            real_session.add(anime)
            # Avto-generatsiya bo'ladigan anime_id ni olish uchun flush
            await real_session.flush() 
            
            # 3. Refresh qilib N+1 oldini olib yuklash (agar epizod qo'shilsa ularni ham inobatga oladi)
            stmt = (select(Anime)
                    .options(selectinload(Anime.genres), selectinload(Anime.episodes))
                    .where(Anime.anime_id == anime.anime_id))
            result = await real_session.execute(stmt)
            loaded_anime = result.scalar_one()
            
            # 4. Yangi anime qo'shilganda qidiruv xaritasiga klaster bo'ylab qo'shamiz
            await valkey.update_single_anime_in_search_map(
                anime_id=loaded_anime.anime_id,
                title=loaded_anime.title,
                year=loaded_anime.year
            )
            
            # Har doim standart Dict qaytaramiz
            return AnimeRepository._serialize_anime(loaded_anime)
            
        except Exception as e:
            logger.error(f"❌ add_anime xatolik: {e}")
            raise

    # ================= ADD ANIME EPISODE =================
    @staticmethod
    async def add_anime_episode(session: Any, anime_id: int, episode_num: int, file_id: str) -> Dict[str, Any]:
        """
        ➕ Yangi epizod qo'shish, joriy anime keshini va klaster L1 keshlarini xavfsiz tozalash
        JIDDIY FIX: commit() olib tashlandi.
        """
        real_session = await AnimeRepository._prepare_session(session)

        try:
            episode = Episode(anime_id=anime_id, episode=episode_num, file_id=file_id)
            real_session.add(episode)
            await real_session.flush()
            
            # 1. Standart anime keshini tozalaymiz (L1 va L2)
            await valkey.invalidate(table="anime_list", obj_id=f"id_{anime_id}", broadcast=True)
            
            # 2. Epizod file_id-sini 3 kunga L1 va L2 keshga yozamiz
            await valkey.set_episode_file_id(
                anime_id=anime_id,
                episode=episode_num,
                file_id=file_id,
                ttl=86400 * 3
            )
            
            logger.info(f"✅ Anime [{anime_id}] ga {episode_num}-qism qo'shildi, kesh tozalandi.")
            
            # Oddiy lug'at (dict) shaklida ma'lumot qaytariladi
            return {"anime_id": anime_id, "episode": episode_num, "file_id": file_id}
            
        except Exception as e:
            logger.error(f"❌ add_anime_episode ichida xatolik: {e}")
            raise

    # ================= UPDATE ANIME =================
    @staticmethod
    async def update_anime(session: Any, anime_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """
        🔄 Anime ma'lumotlarini yangilash, keshni tozalash va qidiruv xaritasini sinxronlash
        JIDDIY FIX: commit() olib tashlandi, Dict qaytaradi.
        """
        real_session = await AnimeRepository._prepare_session(session)

        try:
            stmt = update(Anime).where(Anime.anime_id == anime_id).values(**kwargs).returning(Anime)
            result = await real_session.execute(stmt)
            updated_anime = result.scalar_one_or_none()
            
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
                
                # Yangilangan obyektni olish uchun selectinload
                fetch_stmt = (select(Anime)
                              .options(selectinload(Anime.genres), selectinload(Anime.episodes))
                              .where(Anime.anime_id == anime_id))
                fetch_res = await real_session.execute(fetch_stmt)
                final_anime = fetch_res.scalar_one()
                return AnimeRepository._serialize_anime(final_anime)
                
            return None
        except Exception as e:
            logger.error(f"❌ update_anime ichida xatolik: {e}")
            raise

    # ================= WARM UP ANIME CACHE =================
    @staticmethod
    async def warm_up_anime_search_cache(session: Any):
        """ 🚀 Bot ishga tushganda yoki kesh batamom o'chganda qidiruv keshini to'ldirish """
        real_session = await AnimeRepository._prepare_session(session)
        
        try:
            stmt = select(Anime.anime_id, Anime.title, Anime.year)
            result = await real_session.execute(stmt)
            animes = result.all()

            if not animes:
                return

            cache_data = {str(a.anime_id): f"{a.title} ({a.year})" for a in animes}
            await valkey.set_anime_search_map(cache_data)
            logger.info("🚀 Anime qidiruv xaritasi (Warm-up) klaster tarmog'iga muvaffaqiyatli tarqatildi.")
        except Exception as e:
            logger.error(f"❌ Keshni warm-up qilishda xato: {e}")

    # ================= GET ANIME BY ID =================
    @staticmethod
    async def get_anime_by_id(session: Any, anime_id: int) -> Optional[Dict[str, Any]]:
        """ 🔍 Dual-Layer (L1 local + L2 Valkey) kesh orqali tezkor yuklash """
        obj_key = f"id_{anime_id}"
        
        try:
            cached = await valkey.get(table="anime_list", obj_id=obj_key)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as err:
            logger.warning(f"⚠️ Anime kesh o'qishda xato: {err}")

        real_session = await AnimeRepository._prepare_session(session)

        # Kesh miss bo'lganda bazadan yuklaymiz
        stmt = (
            select(Anime)
            .where(Anime.anime_id == anime_id)
            .options(selectinload(Anime.genres), selectinload(Anime.episodes))
        )
        try:
            result = await real_session.execute(stmt)
            anime = result.scalar_one_or_none()

            if anime:
                anime_dict = AnimeRepository._serialize_anime(anime)
                try:
                    await valkey.set(table="anime_list", obj_id=obj_key, data=anime_dict, ttl=3600)
                except Exception as cache_err:
                    logger.error(f"⚠️ Anime keshga yozishda xato: {cache_err}")
                return anime_dict
                
            return None
        except Exception as e:
            logger.error(f"❌ get_anime_by_id xatolik: {e}")
            raise

    # ================= SEARCH ANIME BY TITLE =================
    @staticmethod
    async def search_anime_by_title(session: Any, query_text: str) -> List[Dict[str, Any]]:
        """ 🔎 Nom bo'yicha qidiruv: Oldin L1/L2 xaritadan, topilmasa DB Fallback """
        query_text = query_text.lower().strip()
        matched_anime_ids = []

        try:
            all_titles = await valkey.get_anime_search_map()
            if all_titles:
                for anime_id_str, full_title in all_titles.items():
                    if query_text in full_title.lower():
                        matched_anime_ids.append(int(anime_id_str))
                        if len(matched_anime_ids) >= 15:
                            break
        except Exception as cache_err:
            logger.error(f"⚠️ Qidiruv keshini o'qishda xatolik: {cache_err}")

        # Agar xaritada bo'lsa, ularni parallel olamiz
        if matched_anime_ids:
            tasks = [AnimeRepository.get_anime_by_id(session, a_id) for a_id in matched_anime_ids]
            fetched_animes = await asyncio.gather(*tasks)
            return [anime for anime in fetched_animes if anime]

        # FALLBACK: DB dan qidirish
        logger.warning(f"⚠️ Keshda moslik topilmadi. DB Fallback ishga tushdi: '{query_text}'")
        
        real_session = await AnimeRepository._prepare_session(session)

        stmt = (
            select(Anime)
            .where(Anime.title.ilike(f"%{query_text}%"))
            .options(selectinload(Anime.genres), selectinload(Anime.episodes))
            .limit(15)
        )
        try:
            result = await real_session.execute(stmt)
            animes = result.scalars().all()
            return [AnimeRepository._serialize_anime(anime) for anime in animes]
        except Exception as e:
            logger.error(f"❌ search_anime_by_title xatolik: {e}")
            raise

    # ================= GET EPISODE FILE =================
    @staticmethod
    async def get_episode_file(session: Any, episode_num: int, anime_id: int) -> Optional[str]:
        """ 🎬 Epizod Telegram file_id-sini L1/L2 kesh orqali tezkor olish """
        try:
            cached_file_id = await valkey.get_episode_file_id(anime_id, episode_num)
            if cached_file_id:
                return cached_file_id
        except Exception as err:
            logger.warning(f"⚠️ Epizod keshini o'qishda xato: {err}")

        real_session = await AnimeRepository._prepare_session(session)

        try:
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
        except Exception as e:
            logger.error(f"❌ get_episode_file xatolik: {e}")
            raise

    # ================= LIST ANIME =================
    @staticmethod
    async def list_anime(session: Any) -> List[Dict[str, Any]]:
        """ 📋 Barcha animelarni olish (Paginatsiya uchun yoki admin panelga) """
        real_session = await AnimeRepository._prepare_session(session)

        if real_session is None:
            logger.error("❌ list_anime: Haqiqiy DB sessiyasi olinmadi.")
            return []

        try:
            stmt = (
                select(Anime)
                .options(selectinload(Anime.genres), selectinload(Anime.episodes))
                .order_by(Anime.anime_id.desc())
            )
            result = await real_session.execute(stmt)
            animes = result.scalars().all()
            return [AnimeRepository._serialize_anime(anime) for anime in animes]
        except Exception as e:
            logger.error(f"❌ list_anime ichida xatolik yuz berdi: {e}")
            raise