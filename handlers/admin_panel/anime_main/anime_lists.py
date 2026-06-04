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
@router.callback_query(AnimePageCallback.filter())  # Sahifalar almashganda ushlab qolish uchun
@router.callback_query(F.data == "list_anime")     # Admin paneldan birinchi marta kirganda
async def list_anime(
    callback: CallbackQuery, 
    callback_data: Optional[AnimePageCallback] = None,
    session: AsyncSession = None, 
    session_pool: async_sessionmaker = None
):
    await callback.answer("📋 Yuklanmoqda...")
    
    # Session yoki Pooldan xavfsiz foydalanish
    if session is None and session_pool is not None:
        async with session_pool() as new_session:
            anime_list = await AnimeRepository.list_anime(session=new_session)
    else:
        anime_list = await AnimeRepository.list_anime(session=session)

    if not anime_list:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))
        await callback.message.edit_text(
            text="📭 Hozircha tizimda birorta ham anime qo'shilmagan.", 
            reply_markup=builder.as_markup()
        )
        return
    
    # Sahifa raqamini xavfsiz aniqlash
    page = callback_data.page if callback_data else 1
    
    # Pagination sozlamalari (Har bir sahifada 5 tadan anime)
    PER_PAGE = 5
    total_anime = len(anime_list)
    total_pages = (total_anime + PER_PAGE - 1) // PER_PAGE
    
    page = max(1, min(page, total_pages))
    
    # Joriy sahifaga tegishli animelarni kesib olish (Slice)
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_anime = anime_list[start_idx:end_idx]
    
    # Tugmalarni yig'ish (InlineKeyboardBuilder)
    builder = InlineKeyboardBuilder()
    
    for anime in page_anime:
        # 🔥 FIX: Nuqta (.) o'rniga dict elementlari ['...'] ishlatilmoqda
        is_completed = anime.get("is_completed", False)
        anime_title = html.escape(anime.get("title", "Nomsiz"))
        anime_year = anime.get("year", "Unknown")
        anime_id = anime.get("anime_id")
        
        status = "🟢" if is_completed else "🔴" 
        text = f"{status} {anime_title} ({anime_year})"
        
        builder.row(
            types.InlineKeyboardButton(
                text=text,
                callback_data=AnimeDetailCallback(
                    anime_id=int(anime_id), 
                    page=page
                ).pack()
            )
        )
    
    # Navigatsiya (Orqaga/Oldinga) tugmalari
    nav_buttons = []
    
    # Oldingi sahifa tugmasi
    if page > 1:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="⬅️ Oldingi", 
                callback_data=AnimePageCallback(page=page - 1).pack()
            )
        )
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="❌", callback_data="noop"))
        
    # Joriy sahifa ko'rsatkichi
    nav_buttons.append(
        types.InlineKeyboardButton(
            text=f"📄 {page}/{total_pages}", 
            callback_data="noop"
        )
    )
    
    # Keyingi sahifa tugmasi
    if page < total_pages:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="Keyingi ➡️", 
                callback_data=AnimePageCallback(page=page + 1).pack()
            )
        )
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="❌", callback_data="noop"))
        
    builder.row(*nav_buttons)
    
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))
    
    text_content = (
        f"📋 <b>ANIMELAR RO'YXATI (Jami: {total_anime} ta)</b>\n\n"
        f"<i>Kerakli animeni tanlab, ustiga bosing:</i>"
    )
    markup_content = builder.as_markup()

    try:
        await callback.message.edit_text(
            text=text_content,
            parse_mode="HTML",
            reply_markup=markup_content
        )
    except TelegramBadRequest as e:
        if "there is no text in the message" in str(e).lower() or "message to edit not found" in str(e).lower():
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            await callback.message.answer(
                text=text_content,
                parse_mode="HTML",
                reply_markup=markup_content
            )
        else:
            if "message is not modified" not in str(e).lower():
                raise e


# =====================================================================
# ANIME DETALLARI (CHOSEN ANIME VIEW) HANDLERI
# =====================================================================
@router.callback_query(AnimeDetailCallback.filter())
async def show_anime_details(callback: CallbackQuery, callback_data: AnimeDetailCallback, session: AsyncSession):
    await callback.answer("📖 Ma'lumotlar yuklanmoqda...")
    
    anime_id = callback_data.anime_id
    current_page = callback_data.page  # Orqaga qaytganda eslab qolish uchun
    
    # 🔥 FIX: Og'ir SELECT query o'rniga, repository'ning kesh himoyasiga ega funksiyasidan foydalanamiz
    # Bu funksiya o'zi avtomat ichidagi janrlarni ham serialize qilib tayyor dict qaytaradi
    anime = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    
    if not anime:
        try:
            await callback.message.edit_text("❌ Kechirasiz, ushbu anime topilmadi.")
        except TelegramBadRequest:
            await callback.message.answer("❌ Kechirasiz, ushbu anime topilmadi.")
        return

    # 🔥 FIX: Ma'lumotlarni dict ko'rinishida kalitlar orqali xavfsiz o'qiymiz
    genres_list = anime.get("genres", [])
    genres_str = ", ".join([html.escape(g) for g in genres_list]) if genres_list else "Mavjud emas"
    
    status_str = "🟢 Tugallangan" if anime.get("is_completed") else "🔴 Davom etmoqda"
    safe_title = html.escape(anime.get("title", "Nomsiz"))
    safe_description = html.escape(anime.get("description") or 'Tavsif kiritilmagan.')
    poster_id = anime.get("poster_id")
    languages = html.escape(anime.get("languages") or 'Noma\'lum')
    episodes_count = anime.get("episode", "Noma'lum")
    episodes_list = anime.get("episodes", [])
    episodes_count = len(episodes_list) if isinstance(episodes_list, list) else 0
    # HTML dizayndagi teglarni to'g'rilab, chiroyli ko'rinishga keltiramiz
    text = (
        f"╔══════════════════╗\n"
        f"       🎬 <b>{safe_title}</b>\n"
        f"╚══════════════════╝\n\n"
        f"📌 <b>Anime Info</b>\n"
        f"╔══════════════════╗\n"
        f"├ 🆔 ID: <code>#{anime_id}</code>\n"  
        f"├ 📅 Year: <b>{anime.get('year', 'Unknown')}</b>\n"
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

    # Inline tugmalarni yig'ish
    builder = InlineKeyboardBuilder()
    
    # Qism qo'shish tugmasi
    builder.row(
        InlineKeyboardButton(
            text="➕ Ushbu animega qism qo'shish", 
            callback_data=f"add_ep_{anime_id}"
        )
    )
    
    # Orqaga qaytish tugmasi (Aynan o'zi kelgan sahifaga qaytadi)
    builder.row(
        InlineKeyboardButton(
            text="🔙 Ro'yxatga qaytish", 
            callback_data=AnimePageCallback(page=current_page).pack()
        )
    )

    markup = builder.as_markup()

    # Xabarni foydalanuvchiga ko'rsatish (Rasm bor yoki yo'qligiga qarab)
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
            logger.error(f"Poster yuborishda xatolik (file_id eskirgan yoki xato): {e}")
            await callback.message.answer(text=text, parse_mode="HTML", reply_markup=markup)
    else:
        try:
            await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                await callback.message.answer(text=text, parse_mode="HTML", reply_markup=markup)