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
@router.callback_query(AnimeDetailCallback.filter())
async def show_anime_details(callback: CallbackQuery, callback_data: AnimeDetailCallback, session: AsyncSession):
    await callback.answer("📖 Ma'lumotlar yuklanmoqda...")
    
    anime_id = callback_data.anime_id
    current_page = callback_data.page  # Orqaga qaytganda eslab qolish uchun
    
    # Repositoriyga so'rov yuboramiz
    anime_data = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    
    if not anime_data:
        try:
            await callback.message.edit_text("❌ Kechirasiz, ushbu anime topilmadi.")
        except TelegramBadRequest:
            await callback.message.answer("❌ Kechirasiz, ushbu anime topilmadi.")
        return

    # 🛡 XAVFSIZLIK POLYGON: Obyekt yoki Dict ekanligini aniqlash va xavfsiz o'qish
    # Agar ob'ekt bo'lsa __dict__ yoki getattr ishlatamiz, dict bo'lsa .get()
    is_dict = isinstance(anime_data, dict)

    def get_val(key: str, default: Any = None) -> Any:
        if is_dict:
            return anime_data.get(key, default)
        return getattr(anime_data, key, default)

    # 1. Sarlavha, yil va tillarni xavfsiz olish
    title = get_val("title", "Nomsiz")
    year = get_val("year", "Noma'lum")
    description = get_val("description", "Tavsif kiritilmagan.")
    poster_id = get_val("poster_id")
    languages = get_val("languages", "Noma'lum")
    is_completed = get_val("is_completed", False)

    # 2. Janrlarni xavfsiz qayta ishlash (Many-to-Many)
    genres_raw = get_val("genres", [])
    genres_list = []
    
    if genres_raw:
        for g in genres_raw:
            # Agar g ob'ekt bo'lsa (Genre modeli), uning .name xususiyatini olamiz
            if hasattr(g, "name"):
                genres_list.append(html.escape(str(g.name)))
            # Agar g shunchaki dict bo'lsa va ichida 'name' bo'lsa
            elif isinstance(g, dict) and "name" in g:
                genres_list.append(html.escape(str(g["name"])))
            # Agar g to'g'ridan-to'g'ri string (janr nomi) bo'lib kelgan bo'lsa
            else:
                genres_list.append(html.escape(str(g)))

    genres_str = ", ".join(genres_list) if genres_list else "Kiritilmagan"

    # 3. Qismlar sonini aniqlash (One-to-Many)
    episodes_raw = get_val("episodes", [])
    if isinstance(episodes_raw, list):
        episodes_count = len(episodes_raw)
    else:
        episodes_count = 0

    # Dizayn qismini shakllantiramiz
    status_str = "🟢 Tugallangan" if is_completed else "🔴 Davom etmoqda"
    safe_title = html.escape(str(title))
    safe_description = html.escape(str(description))

    text = (
        f"╔══════════════════╗\n"
        f"      🎬 <b>{safe_title}</b>\n"
        f"╚══════════════════╝\n\n"
        f"📌 <b>Anime Info</b>\n"
        f"╔══════════════════╗\n"
        f"├ 🆔 ID: <code>#{anime_id}</code>\n"  
        f"├ 📅 Year: <b>{year}</b>\n"
        f"├ ▶️ Episodes: <b>{episodes_count} ta</b>\n"
        f"├ 🚦 Status: <b>{status_str}</b>\n"
        f"├ 🌐 Lang: <b>{languages}</b>\n"
        f"╚══════════════════╝\n"
        f"╔══════════════════╗\n"
        f"└ 🎭 Genres: <b>{genres_str}</b>\n"
        f"╚══════════════════╝\n\n"
        f"📝 <b>Tavsif</b>\n"
        f"<blockquote expandable>"
        f"{safe_description}"
        f"</blockquote>"
    )

    # Inline tugmalar builderi
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="➕ Ushbu animega qism qo'shish", 
            callback_data=f"add_ep_{anime_id}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="🔙 Ro'yxatga qaytish", 
            callback_data=AnimePageCallback(page=current_page).pack()
        )
    )
    markup = builder.as_markup()

    # Rasm yoki Matn ko'rinishida chiqarish logikasi
    if poster_id:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        
        try:
            await callback.message.answer_photo(
                photo=poster_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=markup
            )
        except TelegramBadRequest as e:
            logger.error(f"❌ Poster yuborishda xatolik (eskirgan file_id): {e}")
            await callback.message.answer(text=text, parse_mode="HTML", reply_markup=markup)
    else:
        try:
            await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                await callback.message.answer(text=text, parse_mode="HTML", reply_markup=markup)