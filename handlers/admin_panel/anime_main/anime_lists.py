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


from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.repository import AnimeRepository
from database.connection import AsyncSession, async_sessionmaker

from config import config
from keyboards.inline import anime_menu_kb
from database.repository import AnimeRepository
from database.connection import AsyncSession
from database.models import Anime, Genre


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
    callback_data: Optional[AnimePageCallback] = None,  # 💡 TUZATISH: callback_data ni ixtiyoriy argument sifatida qo'shdik
    session: AsyncSession = None, 
    session_pool: async_sessionmaker = None
):
    await callback.answer("📋 Yuklanmoqda...")
    
    # 💡 AGAR MIDDLEWARE'DAN SESSION 'NONE' KELSA, POOLDAN YANGI SESSYA OCHAMIZ
    if session is None and session_pool is not None:
        async with session_pool() as new_session:
            anime_list = await AnimeRepository.list_anime(session=new_session)
    else:
        # Oddiy holatda uzatilgan sessiyadan foydalanamiz
        anime_list = await AnimeRepository.list_anime(session=session)

    if not anime_list:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))
        await callback.message.edit_text(
            "📭 Hozircha tizimda birorta ham anime qo'shilmagan.", 
            reply_markup=builder.as_markup()
        )
        return
    
    # 💡 TUZATISH: Sahifa raqamini xavfsiz aniqlash
    # Agar callback_data bo'lsa (ya'ni sahifa tugmasi bosilgan bo'lsa), o'sha sahifani oladi.
    # Agar birinchi marta kirayotgan bo'lsa (callback_data yo'q), default 1-sahifa bo'ladi.
    page = callback_data.page if callback_data else 1
    
    # 3. Pagination sozlamalari (Har bir sahifada 5 tadan anime)
    PER_PAGE = 5
    total_anime = len(anime_list)
    total_pages = (total_anime + PER_PAGE - 1) // PER_PAGE
    
    # Sahifa chegaradan chiqib ketmasligi tekshiruvi (Endi xavfsiz ishlaydi!)
    page = max(1, min(page, total_pages))
    
    # Joriy sahifaga tegishli animelarni kesib olish (Slice)
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_anime = anime_list[start_idx:end_idx]
    
    # 4. Tugmalarni yig'ish (InlineKeyboardBuilder)
    builder = InlineKeyboardBuilder()
    
    for anime in page_anime:
        status = "🟢" if anime.is_completed else "🔴" 
        text = f"{status} {anime.title} ({anime.year})"
        
        # Har bir animeni alohida qator qilib tugma sifatida qo'shamiz
        builder.row(
            types.InlineKeyboardButton(
                text=text,
                callback_data=AnimeDetailCallback(
                    anime_id=int(anime.anime_id), 
                    page=page
                ).pack()
            )
        )
    
    # 5. Navigatsiya (Orqaga/Oldinga) tugmalari
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
    
    # 6. Eng pastdagi doimiy "Orqaga" tugmasi (Admin panelga qaytish)
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))
    
    text_content = (
        f"📋 <b>ANIMELAR RO'YXATI (Jami: {total_anime} ta)</b>\n\n"
        f"<i>Kerakli animeni tanlab, ustiga bosing:</i>"
    )
    markup_content = builder.as_markup()

    try:
        # Agar oldingi xabar oddiy matnli bo'lsa, silliqqina edit qiladi
        await callback.message.edit_text(
            text=text_content,
            parse_mode="HTML",
            reply_markup=markup_content
        )
    except TelegramBadRequest as e:
        # Agar oldingi xabar rasmli bo'lsa (ya'ni edit_text xato bersa), 
        # eski rasmli xabarni o'chirib, o'rniga toza matnli ro'yxatni yuboramiz.
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
            # Boshqa kutilmagan Telegram xatoliklari bo'lsa (masalan, message is not modified)
            if "message is not modified" not in str(e).lower():
                raise e











@router.callback_query(AnimeDetailCallback.filter())
async def show_anime_details(callback: CallbackQuery, callback_data: AnimeDetailCallback, session: AsyncSession):
    await callback.answer("📖 Ma'lumotlar yuklanmoqda...")
    
    anime_id = callback_data.anime_id
    current_page = callback_data.page  # Orqaga qaytganimizda aynan o'sha sahifaga qaytish uchun
    
    # 1. Animeni barcha munosabatlari (janrlari) bilan birga bazadan olamiz
    stmt = (
        select(Anime)
        .options(selectinload(Anime.genres))
        .where(Anime.anime_id == anime_id)
    )
    result = await session.execute(stmt)
    anime = result.scalar_one_or_none()
    
    if not anime:
        try:
            await callback.message.edit_text("❌ Kechirasiz, ushbu anime topilmadi.")
        except TelegramBadRequest:
            await callback.message.answer("❌ Kechirasiz, ushbu anime topilmadi.")
        return

    # 2. Janrlarni va statusni formatlaymiz
    genres_str = ", ".join([g.name for g in anime.genres]) if anime.genres else "Mavjud emas"
    status_str = "🟢 Tugallangan" if anime.is_completed else "🔴 Davom etmoqda"
    safe_title = html.escape(anime.title)
    safe_description = html.escape(anime.description or 'Description unavailable.')
    # 3. Anime haqida to'liq ma'lumot matni (HTML chiroyli formatda)
    text = (
        f"╔══════════════════╗\n"
        f"      🎬 <b>{safe_title}</b>\n"
        f"╚══════════════════╝\n\n"

        f"📌 <b>Anime Info</b>\n"
        f"├ 📅 Year: <b>{anime.year}</b>\n"
        f"├ 🚦 Status: <b>{status_str}</b>\n"
        f"├ 🌐 Languages: <b>{anime.languages or 'Unknown'}</b>\n"
        f"└ 🎭 Genres: <b>{genres_str}</b>\n\n"

        f"📝 <b>Tavsif</b>\n"
        f"<blockquote expandable>"
        f"{safe_description}"
        f"</blockquote>"
    )

    # 4. Inline tugmalarni yig'ish
    builder = InlineKeyboardBuilder()
    
    # Qism qo'shish tugmasi
    builder.row(
        InlineKeyboardButton(
            text="➕ Ushbu animega qism qo'shish", 
            callback_data=f"add_ep_{anime.anime_id}"
        )
    )
    
    # 🔙 Orqaga qaytish tugmasi (Aynan kelgan sahifasiga pagination xavfsiz qaytadi)
    builder.row(
        InlineKeyboardButton(
            text="🔙 Ro'yxatga qaytish", 
            callback_data=AnimePageCallback(page=current_page).pack()
        )
    )

    markup = builder.as_markup()

    # 5. Xabarni foydalanuvchiga ko'rsatish (Rasm bor yoki yo'qligiga qarab)
    if anime.poster_id:
        try:
            # 🔥 UX FIX: Eski matnli xabarni o'chirganda keladigan "Message to delete not found" 
            # xatosini try-except orqali silliq ushlab qolamiz.
            await callback.message.delete()
        except TelegramBadRequest:
            pass  # Agar xabar allaqachon o'chirilgan bo'lsa, xatolik bermaydi
        
        try:
            await callback.message.answer_photo(
                photo=anime.poster_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=markup
            )
        except TelegramBadRequest as e:
            logger.error(f"Poster yuborishda xatolik (Balki file_id eskirgan): {e}")
            # Agar rasm yuborishda muammo bo'lsa (masalan file_id noto'g'ri), matn ko'rinishida yuboramiz
            await callback.message.answer(text=text, parse_mode="HTML", reply_markup=markup)
    else:
        # Agar poster bo'lmasa xabarni shunchaki tahrirlaymiz
        try:
            await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                await callback.message.answer(text=text, parse_mode="HTML", reply_markup=markup)