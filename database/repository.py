import json
import logging
import asyncio

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from database.models import DBUser, Channel, List, Anime, Episode, Genre, anime_genres  # Modellar yo'li

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
        










 

logger = logging.getLogger("AnimeRepository")

class AnimeRepository:

    @staticmethod
    async def add_anime(session: Any, title: str, poster_id: str, year: int, is_completed: bool, 
                        genres: List[str], description: str, languages: str, episodes: List[Dict[str, Any]]) -> Anime:
        """
        ➕ Yangi anime qo'shish (Xavfsiz sessiya va Outbox/Kesh moslashuvi bilan)
        """
        try:
            # SafeSession obyektini tayyorlashga majburlash (Proxy bo'lsa)
            if hasattr(session, "_ensure_session"):
                await session._ensure_session()

            # 1. Obyektni yaratish
            anime = Anime(
                title=title, 
                poster_id=poster_id, 
                year=year, 
                is_completed=is_completed,
                description=description,
                languages=languages
            )
            
            session.add(anime)
            await session.flush() # Anime ID sini olish uchun

            # 2. Janrlarni tekshirish va optimallashgan holatda bog'lash
            existing_genres_res = await session.execute(select(Genre).where(Genre.name.in_(genres)))
            existing_genres = {g.name: g for g in existing_genres_res.scalars().all()}

            new_genres_to_add = []
            for genre_name in genres:
                if genre_name in existing_genres:
                    anime.genres.append(existing_genres[genre_name])
                else:
                    new_genre = Genre(name=genre_name)
                    new_genres_to_add.append(new_genre)
                    anime.genres.append(new_genre)

            if new_genres_to_add:
                session.add_all(new_genres_to_add)
                await session.flush() # Barcha yangi janrlarni bitta so'rovda flush qilamiz

            # 3. Tranzaksiyani yakunlash
            await session.commit()
            
            # 🔥 N+1 muammosini oldini olish uchun munosabatlarni srazu refresh qilamiz
            await session.refresh(anime, attribute_names=["genres", "episodes"])

            # 4. Qidiruv xaritasini yangilash
            await valkey.update_single_anime_in_search_map(
                anime_id=anime.anime_id,
                title=anime.title,
                year=anime.year
            )
            
            return anime
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ add_anime ichida xatolik: {e}")
            raise e
        
    @staticmethod
    async def add_anime_episode(session: Any, anime_id: int, episode_num: int, file_id: str) -> Optional[Episode]:
        """
        ➕ Yangi epizod qo'shish va kesh zanjirini xavfsiz yangilash
        """
        try:
            # SafeSession obyektini tayyorlashga majburlash (Proxy bo'lsa)
            if hasattr(session, "_ensure_session"):
                await session._ensure_session()

            episode = Episode(anime_id=anime_id, episode=episode_num, file_id=file_id)
            session.add(episode)
            await session.commit()
            
            # 🔥 Kesh zanjirlarini tozalash va yangilash
            await valkey.invalidate(table="anime_list", obj_id=f"id_{anime_id}")
            await valkey.set_episode_file_id(
                anime_id=anime_id,
                episode=episode_num,
                file_id=file_id,
                ttl=86400 * 3  # 3 kunlik tezkor kesh
            )
            
            logger.info(f"✅ Anime [{anime_id}] ga {episode_num}-qism qo'shildi va keshlar yangilandi.")
            return episode
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ add_anime_episode ichida xatolik: {e}")
            raise e
        
    @staticmethod
    async def update_anime(session: Any, anime_id: int, **kwargs) -> Optional[Anime]:
        """
        🔄 Anime ma'lumotlarini yangilash va keshni xavfsiz tozalash
        """
        try:
            if hasattr(session, "_ensure_session"):
                await session._ensure_session()

            stmt = update(Anime).where(Anime.anime_id == anime_id).values(**kwargs).returning(Anime)
            result = await session.execute(stmt)
            updated_anime = result.scalar_one_or_none()
            await session.commit()
            
            if updated_anime:
                await valkey.invalidate(table="anime_list", obj_id=f"id_{anime_id}")
                
                if "title" in kwargs or "year" in kwargs:
                    await valkey.update_single_anime_in_search_map(
                        anime_id=updated_anime.anime_id,
                        title=updated_anime.title,
                        year=updated_anime.year
                    )
                logger.info(f"🧹 Anime [{anime_id}] keshlari muvaffaqiyatli tozalandi.")
                
            return updated_anime
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ update_anime ichida xatolik: {e}")
            raise e

    @staticmethod
    async def warm_up_anime_search_cache(session: AsyncSession):
        """ 🚀 Bot ishga tushganda barcha anime nomlarini qidiruv keshiga yuklash """
        try:
            stmt = select(Anime.anime_id, Anime.title, Anime.year)
            result = await session.execute(stmt)
            animes = result.all()

            if not animes:
                return

            cache_data = {str(a.anime_id): f"{a.title} ({a.year})" for a in animes}
            await valkey.set_anime_search_map(cache_data)
            logger.info("🚀 Anime qidiruv keshi (Warm-up) muvaffaqiyatli yakunlandi.")
        except Exception as e:
            logger.error(f"❌ Keshni warm-up qilishda xato: {e}")

    @staticmethod
    async def get_anime_by_id(session: Any, anime_id: int) -> Optional[Dict[str, Any]]:
        """ 🔍 Anime ID bo'yicha keshdan yoki bazadan (Eager Loading bilan) ma'lumot olish """
        obj_key = f"id_{anime_id}"
        try:
            cached = await valkey.get(table="anime_list", obj_id=obj_key)
            if cached:
                return cached.copy()
        except Exception as err:
            logger.warning(f"⚠️ Anime kesh o'qishda xato: {err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()

        # 🔥 FIX: N+1 muammosini yo'qotish uchun genres va episodes jadvallarini srazu birga yuklaymiz (Joined/SelectIn Load)
        stmt = (
            select(Anime)
            .where(Anime.anime_id == anime_id)
            .options(selectinload(Anime.genres), selectinload(Anime.episodes))
        )
        result = await session.execute(stmt)
        anime = result.scalar_one_or_none()

        if anime:
            anime_dict = AnimeRepository._serialize_anime(anime)
            try:
                await valkey.set(table="anime_list", obj_id=obj_key, data=anime_dict, ttl=3600)
            except Exception as cache_err:
                logger.error(f"⚠️ Anime keshga yozishda xato: {cache_err}")
            return anime_dict
        return None

    @staticmethod
    async def search_anime_by_title(session: Any, query_text: str) -> List[Dict[str, Any]]:
        """ 🔎 Nom bo'yicha birinchi KESHdan, topilmasa BAZAdan qisman qidirish """
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

        if matched_anime_ids:
            tasks = [AnimeRepository.get_anime_by_id(session, a_id) for a_id in matched_anime_ids]
            fetched_animes = await asyncio.gather(*tasks)
            return [anime for anime in fetched_animes if anime]

        # FALLBACK: Bazadan qidirganda ham munosabatlarni srazu yuklaymiz (N+1 oldini olish)
        logger.warning(f"⚠️ Keshdan topilmadi. Bazadan qidirilmoqda: '{query_text}'")
        stmt = (
            select(Anime)
            .where(Anime.title.ilike(f"%{query_text}%"))
            .options(selectinload(Anime.genres), selectinload(Anime.episodes))
            .limit(15)
        )
        result = await session.execute(stmt)
        animes = result.scalars().all()
        
        # Fon rejimida kesh xaritani yangilab qo'yamiz
        asyncio.create_task(AnimeRepository.warm_up_anime_search_cache(session))

        return [AnimeRepository._serialize_anime(anime) for anime in animes]

    @staticmethod
    async def get_episode_file(session: Any, episode_num: int, anime_id: int) -> Optional[str]:
        """ 🎬 Epizodning Telegram file_id sini olish """
        try:
            cached_file_id = await valkey.get_episode_file_id(anime_id, episode_num)
            if cached_file_id:
                return cached_file_id
        except Exception as err:
            logger.warning(f"⚠️ Epizod keshini o'qishda xato: {err}")

        if hasattr(session, "_ensure_session"):
            await session._ensure_session()

        stmt = select(Episode).where(Episode.anime_id == anime_id, Episode.episode == episode_num)
        result = await session.execute(stmt)
        ep = result.scalar_one_or_none()

        if ep:
            try:
                await valkey.set_episode_file_id(anime_id, episode_num, ep.file_id, ttl=86400)
            except Exception:
                pass
            return ep.file_id
        return None

    @staticmethod
    def _serialize_anime(anime: Anime) -> Dict[str, Any]:
        """ 🔄 SQLAlchemy modelini JSON/Keshbop dict formatiga o'tkazish (Xavfsiz va tez) """
        # 💡 DIQQAT: selectinload ishlatganimiz sababli bu yerda yashirin so'rovlar (N+1) tugatildi!
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