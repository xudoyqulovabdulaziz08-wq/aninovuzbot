import logging
import html
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

    # 4. Tugmalarni yaratish
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Qism qo'shish", callback_data=f"add_ep_{anime_id}")
    builder.button(text="✏️ Tahrirlash", callback_data=f"edit_anime_{anime_id}")
    builder.button(text="▶️ Qismlar", callback_data=f"view_eps_{anime_id}")
    
    # 🔙 ORQAGA TUGMASI (O'chirish logikasini callback_data orqali ajratib olish uchun maxsus prefiks)
    # Masalan, back_page_1 ko'rinishida yuboriladi
    builder.button(text="🔙 Orqaga", callback_data=f"back_page_{current_page}")
    builder.adjust(2)
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

# =====================================================================
# 🔙 ORQAGA TUGMASI BOSILGANDA RASMNI O'CHIRIB, RO'YXATNI QAYTA CHIQARISH
# =====================================================================
