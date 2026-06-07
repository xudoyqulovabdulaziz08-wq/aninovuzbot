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
async def list_anime(
    callback: CallbackQuery,
    callback_data: Optional[AnimePageCallback] = None,
    session: Any = None,
    session_pool: Any = None
):
    await callback.answer("📋 Yuklanmoqda...")

    # 1. Ma'lumotni Repository'dan olish
    try:
        if session is None and session_pool is not None:
            async with session_pool() as new_session:
                anime_list = await AnimeRepository.list_anime(session=new_session)
        else:
            anime_list = await AnimeRepository.list_anime(session=session)
    except Exception as e:
        logger.error(f"❌ Animelar ro'yxatini yuklashda xato: {e}")
        return await callback.message.answer("❌ Tizimda xatolik yuz berdi.")

    if not anime_list:
        await callback.message.edit_text("📭 Hozircha anime qo'shilmagan.", reply_markup=None)
        return

    # 2. Pagination logikasi
    page = callback_data.page if callback_data else 1
    PER_PAGE = 5
    total_anime = len(anime_list)
    total_pages = (total_anime + PER_PAGE - 1) // PER_PAGE
    page = max(1, min(page, total_pages))
    
    page_anime = anime_list[(page - 1) * PER_PAGE : page * PER_PAGE]

    # 3. Inline tugmalarni shakllantirish
    builder = InlineKeyboardBuilder()
    
    for anime in page_anime:
        # Xavfsiz ma'lumotlar olish
        anime_id = anime.get("anime_id")
        title = str(anime.get("title", "Nomsiz"))
        year = str(anime.get("year", "Noma'lum"))
        is_completed = anime.get("is_completed", False)
        status = "🟢" if is_completed else "🔴"

        # 🔥 Tugma nomini tozalash va formatlash (Limit: 45 belgi)
        # ID va Yil tugmada ko'rinmaydi, ular faqat callback_data'da bo'ladi!
        display_title = title if len(title) <= 40 else title[:37] + "..."
        button_text = f"{status} {display_title}"

        builder.row(
            types.InlineKeyboardButton(
                text=button_text,
                callback_data=AnimeDetailCallback(anime_id=int(anime_id), page=page).pack()
            )
        )

    # 4. Navigatsiya tugmalari (Pagination)
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
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))

    # 5. Xavfsiz xabar chiqarish
    text_content = (
        f"📋 <b>ANIMELAR RO'YXATI</b>\n"
        f"Jami: <b>{total_anime}</b> ta anime topildi.\n\n"
        f"<i>Tanlash uchun bosing:</i>"
    )

    try:
        await callback.message.edit_text(
            text=text_content, parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            await callback.message.answer(text=text_content, parse_mode="HTML", reply_markup=builder.as_markup())

# =====================================================================
# ANIME DETALLARI (CHOSEN ANIME VIEW) HANDLERI
# =====================================================================


@router.callback_query(AnimeDetailCallback.filter())
async def show_anime_details(callback: CallbackQuery, callback_data: AnimeDetailCallback, session: Any):
    await callback.answer("📖") # Qisqa javob tezroq ishlaydi
    
    anime_id = callback_data.anime_id
    current_page = callback_data.page
    
    # 1. Keshdan yoki bazadan ma'lumot olish (Repository kesh bilan integratsiyalangan deb faraz qilamiz)
    anime_data = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    
    if not anime_data:
        await callback.message.answer("❌ Anime topilmadi.")
        return

    # Xavfsiz atribut/key o'qish (Helper funksiyani class ichiga yoki tashqariga chiqargan ma'qul)
    def get_v(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    # 2. Data tozalash
    title = html.escape(get_v(anime_data, "title", "Nomsiz"))
    year = get_v(anime_data, "year", "Noma'lum")
    poster_id = get_v(anime_data, "poster_id")
    is_completed = get_v(anime_data, "is_completed", False)
    
    # Genre va Epizodlar
    genres = get_v(anime_data, "genres", [])
    genres_list = [html.escape(g.name if hasattr(g, "name") else str(g)) for g in genres]
    genres_str = ", ".join(genres_list) if genres_list else "Kiritilmagan"
    
    episodes = get_v(anime_data, "episodes", [])
    ep_count = len(episodes) if isinstance(episodes, list) else 0
    
    # Tavsifni tozalash va qirqish (Caption 1024 limit uchun)
    raw_desc = get_v(anime_data, "description", "Tavsif yo'q.")
    clean_desc = html.escape(str(raw_desc))
    if len(clean_desc) > 600:
        clean_desc = clean_desc[:597] + "..."

    # 3. Matnni shakllantirish
    text = (
        f"🎬 <b>{title}</b>\n\n"
        f"🆔 ID: <code>#{anime_id}</code>\n"
        f"📅 Yil: <b>{year}</b>\n"
        f"▶️ Qismlar: <b>{ep_count} ta</b>\n"
        f"🚦 Status: <b>{'🟢 Tugallangan' if is_completed else '🔴 Davom etmoqda'}</b>\n"
        f"🎭 Janrlar: <i>{genres_str}</i>\n\n"
        f"📝 <b>Tavsif:</b>\n"
        f"<blockquote expandable>{clean_desc}</blockquote>"
    )

    # 4. Tugmalar
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Qism qo'shish", callback_data=f"add_ep_{anime_id}")
    builder.button(text="✏️ Tahrirlash", callback_data=f"edit_anime_{anime_id}")
    builder.button(text="▶️ Qismlar", callback_data=f"view_eps_{anime_id}")
    builder.button(text="🔙 Orqaga", callback_data=AnimePageCallback(page=current_page).pack())
    builder.adjust(2) # 2 ta tugmadan qatorga joylash
    markup = builder.as_markup()

    # 5. Xavfsiz render (Rasm yoki Matn)
    try:
        if poster_id:
            # Rasm bo'lsa, edit_media ishlatish tezroq va chiroyliroq
            try:
                await callback.message.edit_media(
                    media=types.InputMediaPhoto(media=poster_id, caption=text, parse_mode="HTML"),
                    reply_markup=markup
                )
            except TelegramBadRequest:
                # Agar o'xshamasa (masalan, fayl ID eskirgan bo'lsa), yangisini yuboramiz
                await callback.message.delete()
                await callback.message.answer_photo(photo=poster_id, caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Render Error: {e}")