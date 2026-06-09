import logging
import html
from sqlalchemy import select
from sqlalchemy.orm import selectinload
# Masalan, modellar models papkasi ichida bo'lsa:
from database.models import Anime, Genre, Episode
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from typing import Any, Optional
from aiogram.filters.callback_data import CallbackData

from database.repository import AnimeRepository
from database.connection import AsyncSession, async_sessionmaker

router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


class AnimePageCallback(CallbackData, prefix="anime_page"):
    page: int

class AnimeDetailCallback(CallbackData, prefix="anime_detail"):
    anime_id: int
    page: int


# =====================================================================
# ANIMELAR RO'YXATI VA SAHIFALASH (PAGINATION) HANDLERI
# =====================================================================
@router.callback_query(AnimePageCallback.filter())
@router.callback_query(F.data == "list_anime")
@router.callback_query(F.data.startswith("back_page_"))  # 🔙 Tafsilotlardan qaytish ham shu yerga keladi
async def list_anime(
    callback: CallbackQuery,
    callback_data: Optional[AnimePageCallback] = None,
    session: Any = None,
    session_pool: Any = None
):
    await callback.answer("📋 Yuklanmoqda...")

    # 1. Sahifa raqamini aniqlash
    page = 1
    if callback_data:
        page = callback_data.page
    elif callback.data.startswith("back_page_"):
        try:
            page = int(callback.data.split("_")[-1])
        except (IndexError, ValueError):
            page = 1

    # 2. Ma'lumotni Repository'dan olish
    try:
        if session is None and session_pool is not None:
            async with session_pool() as new_session:
                anime_list = await AnimeRepository.list_anime(session=new_session)
        else:
            anime_list = await AnimeRepository.list_anime(session=session)
    except Exception as e:
        logger.error(f"❌ Animelar ro'yxatini yuklashda xato: {e}")
        return await callback.message.answer("❌ Tizimda xatolik yuz berdi.")

    # 3. Agar ro'yxat bo'sh bo'lsa
    if not anime_list:
        # Xabar rasm bo'lsa o'chirib yangi tashlaymiz, matn bo'lsa edit qilamiz
        if callback.message.photo or callback.message.document:
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass
            return await callback.message.answer("📭 Hozircha anime qo'shilmagan.")
        else:
            return await callback.message.edit_text("📭 Hozircha anime qo'shilmagan.", reply_markup=None)

    # 4. Pagination (Sahifalash) logikasi
    PER_PAGE = 5
    total_anime = len(anime_list)
    total_pages = (total_anime + PER_PAGE - 1) // PER_PAGE
    page = max(1, min(page, total_pages))
    
    page_anime = anime_list[(page - 1) * PER_PAGE : page * PER_PAGE]

    # Atributlarni xavfsiz o'qish helper funktsiyasi
    def get_v(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    # 5. Inline tugmalarni shakllantirish
    builder = InlineKeyboardBuilder()
    
    for anime in page_anime:
        anime_id = get_v(anime, "anime_id")
        title = str(get_v(anime, "title", "Nomsiz"))
        is_completed = get_v(anime, "is_completed", False)
        status = "🟢" if is_completed else "🔴"

        display_title = title if len(title) <= 35 else title[:32] + "..."
        button_text = f"{status} {display_title}"

        builder.row(
            types.InlineKeyboardButton(
                text=button_text,
                callback_data=AnimeDetailCallback(anime_id=int(anime_id), page=page).pack()
            )
        )

    # 6. Navigatsiya tugmalari (Pagination)
    nav_buttons = []
    if page > 1:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️", callback_data=AnimePageCallback(page=page - 1).pack()))
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="🔹", callback_data="noop"))
        
    nav_buttons.append(types.InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(types.InlineKeyboardButton(text="➡️", callback_data=AnimePageCallback(page=page + 1).pack()))
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="🔹", callback_data="noop"))
        
    builder.row(*nav_buttons)
    builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))

    # 7. Xabar matni
    text_content = (
        f"📋 <b>ANIMELAR RO'YXATI</b>\n"
        f"<blockquote expandable>Jami: <b>{total_anime}</b> ta anime topildi.</blockquote>\n\n"
        f"<i>Tanlash uchun bosing:</i>"
    )

    # 🔥 8. SMART HYBRID RENDER (Ham edit, ham delete/send uchun universal qism)
    # Agar joriy xabarda RASM bo'lsa (ya'ni tafsilotlar sahifasidan orqaga qaytgan bo'lsa)
    if callback.message.photo or callback.message.document:
        try:
            await callback.message.delete() # Rasmli eski xabarni o'chiramiz
        except TelegramBadRequest:
            pass
        # Toza matn ko'rinishida yangi xabar yuboramiz
        await callback.message.answer(
            text=text_content, 
            parse_mode="HTML", 
            reply_markup=builder.as_markup()
        )
    
    # Agar joriy xabar ODDIY MATN bo'lsa (ya'ni bosh menyudan edit bo'lib kelayotgan bo'lsa yoki pagination bosilganda)
    else:
        try:
            await callback.message.edit_text(
                text=text_content, 
                parse_mode="HTML", 
                reply_markup=builder.as_markup()
            )
        except TelegramBadRequest as e:
            # Agar kutilmagan xato bo'lsa (masalan xabar o'zgarmagan bo'lsa), fallback sifatida yangi xabar yuboradi
            if "message is not modified" not in str(e).lower():
                await callback.message.answer(
                    text=text_content, 
                    parse_mode="HTML", 
                    reply_markup=builder.as_markup()
                )
# =====================================================================
# ANIME DETALLARI (CHOSEN ANIME VIEW) HANDLERI
# =====================================================================


@router.callback_query(AnimeDetailCallback.filter())
async def show_anime_details(callback: CallbackQuery, callback_data: AnimeDetailCallback, session: Any):
    await callback.answer("📖")
    
    anime_id = callback_data.anime_id
    current_page = callback_data.page
    
    # 1. Ma'lumotni bazadan olish
    anime_data = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    
    if not anime_data:
        return await callback.message.answer("❌ Anime topilmadi.")

    # Atributlarni xavfsiz o'qish funksiyasi
    def get_v(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    # 2. Ma'lumotlarni tozalash va tayyorlash
    title = html.escape(get_v(anime_data, "title", "Nomsiz"))
    year = get_v(anime_data, "year", "Noma'lum")
    poster_id = get_v(anime_data, "poster_id")
    languages = get_v(anime_data, "languages", "O'zbekcha")
    safe_languages = html.escape(str(languages))
    
    # Janrlarni formatlash
    genres = get_v(anime_data, "genres", [])
    genres_list = [html.escape(g.name if hasattr(g, "name") else str(g)) for g in genres]
    genres_str = ", ".join(genres_list) if genres_list else "Kiritilmagan"
    
    # Epizodlar soni
    episodes = get_v(anime_data, "episodes", [])
    ep_count = len(episodes) if isinstance(episodes, list) else 0
    
    # Tavsif matnini 1024 limitiga qarab dinamik qirqish
    # (Ramkalar va ma'lumotlar hajmi taxminan 450 belgi oladi, xavfsizlik uchun tavsifni 500 ga cheklaymiz)
    raw_desc = get_v(anime_data, "description", "Tavsif yo'q.")
    if len(raw_desc) > 500:
        raw_desc = raw_desc[:497] + "..."
    safe_desc = html.escape(str(raw_desc))

    # 3. CHANCHAL SHABLON MATNI (Tavsifni ham ichiga qo'shdik 🔥)
    text = (
        f"╔══════════════════╗\n"
        f"     🎬 <b>{title}</b>\n"
        f"╚══════════════════╝\n\n"
        f"📌 <b>Anime haqida ma'lumot:</b>\n"
        f"╔══════════════════╗\n"
        f"├ 🆔 Kod: <code>#{anime_id}</code>\n"  # FIX: anime.anime_id xatosi to'g'rilandi
        f"├ 📅 Yil: <b>{year}</b>\n"
        f"├ ▶️ Qism: <b>{ep_count}</b> \n"
        f"├ 🌐 Til: <b>{safe_languages}</b>\n"
        f"╚══════════════════╝\n"
        f"╔══════════════════╗\n"
        f"  🔮 Janrlar: <i>{genres_str}</i>\n"
        f"╚══════════════════╝\n\n"
        f"📝 <b>Tavsif:</b>\n"
        f"<blockquote expandable>{safe_desc}</blockquote>"  # FIX: Tavsif matnga biriktirildi
    )

    # 4. Tugmalarni yaratish (Yaxshilangan UX 🚀)
    builder = InlineKeyboardBuilder()

    # 1-qator: Eng asosiy harakat (Kanalga e'lon qilish) - To'liq kenglikda, ajralib turishi uchun
    builder.row(
        types.InlineKeyboardButton(text="📢 Kanalga e'lon qilish", callback_data=f"publish_retry_anime_{anime_id}")
    )

    # 2-qator: Kontent bilan ishlash (Qismlarni ko'rish va yangi qism yuklash) - Yonma-yon
    builder.row(
        types.InlineKeyboardButton(text="▶️ Qismlarni ko'rish", callback_data=f"view_eps_{anime_id}"),
        types.InlineKeyboardButton(text="➕ Qism qo'shish", callback_data=f"add_ep_{anime_id}")
    )

    # 3-qator: Boshqaruv va Navigatsiya (Tahrirlash va Orqaga qaytish) - Yonma-yon
    builder.row(
        types.InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"edit_anime_{anime_id}"),
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"back_page_{current_page}")
    )

    # DIQQAT: builder.adjust() ishlatmang! Chunki biz .row() orqali qatorlarni o'zimiz chiroyli qilib taqsimladik.
    markup = builder.as_markup()

    # 5. ESKI XABARNI O'CHIRIB YANGI RENDER QILISH (Delete & Send)
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass  # Agar xabar allaqachon o'chirilgan bo'lsa, xatolikni o'tkazib yuboramiz

    if poster_id:
        await callback.message.answer_photo(
            photo=poster_id, 
            caption=text, 
            parse_mode="HTML", 
            reply_markup=markup
        )
    else:
        await callback.message.answer(
            text=text, 
            parse_mode="HTML", 
            reply_markup=markup
        )






@router.callback_query(F.data.startswith("publish_retry_anime_"))
async def retry_publish_anime_to_channel(callback: CallbackQuery, session: Any):
    """ 
    📢 AnimeRepository standartlariga mos ravishda, bazadagi mavjud animeni 
    hech qanday yangi ma'lumot yozmasdan @Aninovuz kanaliga qayta e'lon qiladi.
    """
    await callback.answer("📢 Kanalga qayta e'lon qilish boshlandi...")
    
    # 1. Callback_data ichidan anime_id ni ajratib olish
    try:
        anime_id = int(callback.data.rsplit("_", 1)[-1])
    except (IndexError, ValueError):
        return await callback.answer("❌ Anime ID aniqlanmadi!", show_alert=True)

    loading_text = "⏳ <code>Anime ma'lumotlari repozitoriydan olinmoqda...</code>"
    
    # Vizual yuklanish holatini xavfsiz boshqarish (Rasm yoki Matnligiga qarab)
    try:
        current_msg = await callback.message.edit_text(text=loading_text, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            current_msg = await callback.message.edit_caption(caption=loading_text, parse_mode="HTML")
        except TelegramBadRequest:
            current_msg = await callback.message.answer(text=loading_text, parse_mode="HTML")

    try:
        # 2. SEANS TAYYORLASH (Sizning AnimeRepository logikangiz asosida)
        # SafeSession proxy yoki oddiy seansligini tekshirib, haqiqiysini ajratib oladi
        if hasattr(AnimeRepository, "_prepare_session"):
            real_session = await AnimeRepository._prepare_session(session)
        else:
            real_session = session._session if hasattr(session, "_session") else session

        # 3. ANIMENI BAZADAN BARCHA ALOQALARI BILAN YUKLASH (Eager Loading)
        stmt = (
            select(Anime)
            .options(
                selectinload(Anime.genres),
                selectinload(Anime.episodes)
            )
            .where(Anime.anime_id == anime_id)
        )
        result = await real_session.execute(stmt)
        anime_obj = result.scalar_one_or_none()
        
        if not anime_obj:
            admin_builder = InlineKeyboardBuilder()
            admin_builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
            await current_msg.edit_text("❌ Xatolik: Ushbu anime bazadan topilmadi.", reply_markup=admin_builder.as_markup())
            return

        # 4. REPOZITORIY STANDARTI BO'YICHA SERIALIZATSIYA
        # _serialize_anime orqali ma'lumotlarni xavfsiz dict formatiga o'tkazamiz
        anime_data = AnimeRepository._serialize_anime(anime_obj)

        # 5. DICT ICHIDAN MA'LUMOTLARNI XAVFSIZ O'QISH
        title = html.escape(str(anime_data.get("title", "Nomsiz")))
        year = anime_data.get("year", "Noma'lum")
        poster_id = anime_data.get("poster_id")
        languages = html.escape(str(anime_data.get("languages", "O'zbekcha")))
        
        # Janrlar ro'yxati (Sizning serializer g.name'larni string list qilib qaytaradi)
        genres_list = anime_data.get("genres", [])
        genres_str = ", ".join([html.escape(g) for g in genres_list]) if genres_list else "Kiritilmagan"
        
        # Epizodlar soni
        episodes_list = anime_data.get("episodes", [])
        episodes_count = len(episodes_list) if isinstance(episodes_list, list) else 0
        
        status_str = "🟢 Tugallangan" if anime_data.get("is_completed", False) else "🔴 Davom etmoqda"

        # 6. SHABLON MATNINI SHAKLLANTIRISH
        base_caption = (
            f"╔══════════════════╗\n"
            f"     🎬 <b>{title}</b>\n"
            f"╚══════════════════╝\n\n"
            f"📌 <b>Anime haqida ma'lumot:</b>\n"
            f"╔══════════════════╗\n"
            f"├ 🆔 Kod: <code>#{anime_id}</code>\n"  
            f"├ 📅 Yil: <b>{year}</b>\n"
            f"├ ▶️ Qism: <b>{episodes_count}</b> \n"
            f"├ 🚦 Status: <b>{status_str}</b>\n"
            f"├ 🌐 Til: <b>{languages}</b>\n"
            f"╚══════════════════╝\n"
            f"╔══════════════════╗\n"
            f"  🔮 Janrlar: <i>{genres_str}</i>\n"
            f"╚══════════════════╝\n\n"
            f"📝 <b>Tavsif:</b>\n"
        )
        
        raw_description = anime_data.get("description", "Tavsif kiritilmagan.")
        
        # Telegram Caption (1024 belgi) limitini dinamik hisoblash va qirqish
        if poster_id:
            max_description_allowed = 1024 - len(base_caption) - 35
            if len(raw_description) > max_description_allowed:
                raw_description = raw_description[:max_description_allowed] + "..."
                
        safe_description = html.escape(raw_description)
        caption = base_caption + f"<blockquote expandable>{safe_description}</blockquote>"
        
        # 7. DEEP-LINK TUGMASI (Kanal foydalanuvchilarini botga yo'naltirish uchun)
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username
        
        channel_builder = InlineKeyboardBuilder()
        channel_builder.row(
            types.InlineKeyboardButton(
                text="🎬 Animeni ko'rish", 
                url=f"https://t.me/{bot_username}?start=anime_{anime_id}"
            )
        )

        # 📢 8. @Aninovuz KANALIGA CHIQARISH (Rasm mavjudligiga qarab)
        if poster_id:
            await callback.bot.send_photo(
                chat_id="@Aninovuz", 
                photo=poster_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=channel_builder.as_markup()
            )
        else:
            await callback.bot.send_message(
                chat_id="@Aninovuz", 
                text=caption,
                parse_mode="HTML",
                reply_markup=channel_builder.as_markup()
            )
        
        # 9. Admin uchun muvaffaqiyat hisoboti interfeysi
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        
        success_text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "   📢 KANALGA MUVAFFAQLI JOYLANDI!\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"🎬 <b>Anime:</b> <code>{title}</code>\n"
            f"🚀 <b>Kanal:</b> @Aninovuz\n\n"
            "───────────────────────\n"
            "✅ <i>Baza bilan hech qanday yozish yoki o'chirish amallari bajarilmadi. Faqat repozitoriydan o'qilib, kanalga yo'llandi.</i>"
        )
        
        try:
            await current_msg.edit_text(text=success_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=success_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
            
    except Exception as e:
        logger.error(f"❌ Qayta e'lon qilishda xatolik (retry_publish): {e}")
        
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        
        error_text = (
            f"⚠️ <b>Kanalga post chiqarishda xatolik yuz berdi!</b>\n\n"
            f"<b>Xato matni:</b> <code>{html.escape(str(e))}</code>\n\n"
            f"💡 <i>Eslatma: Bot kanalda admin ekanligini va post joylash huquqlari ochiqligini tekshiring.</i>"
        )
        try:
            await current_msg.edit_text(text=error_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())