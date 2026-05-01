import pytz
import logging
from datetime import datetime, timezone
from aiogram import types, F, Router
from typing import Any, Union  # ✅ To'g'risi shu
from sqlalchemy import select, desc
from database.models import DBUser, Anime
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
from database.cache import valkey
router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)



from typing import Union

@router.message(F.text == "🌟 Reyting")
@router.callback_query(F.data == "reyting_menu")
async def ranked_full(event: Union[types.Message, types.CallbackQuery], user: DBUser, session: AsyncSession = None):
    # Event turini aniqlaymiz
    is_callback = isinstance(event, types.CallbackQuery)
    message = event.message if is_callback else event

    text = (
        f"🌟 <b>REYTING BO'LIMI</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"Kerakli bo'limni tanlang:\n"
        f"▫️ <b>Anime reyting</b> — Eng ko'p ko'rilgan animelar\n"
        f"▫️ <b>User reyting</b> — Eng ko'p do'stini taklif qilganlar"
        f"Tez orada juda ko'plab foydalnuvchilar istagan <b>Reyting</b> qishiladi"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎬 Anime reyting", callback_data="Anime_ranked")],
        [types.InlineKeyboardButton(text="🏆 Top foydalanuvchilar", callback_data="User_ranked")],
        
    ])

    if is_callback:
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
        await event.answer()
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")



from sqlalchemy import select, desc, func, cast, Float, case
from aiogram.exceptions import TelegramBadRequest

@router.callback_query(F.data == "Anime_ranked")
async def anime_rank(callback: types.CallbackQuery, session: AsyncSession):
    
    avg_rating_raw = Anime.rating_sum / func.nullif(Anime.rating_count, 0)
    avg_rating = func.coalesce(avg_rating_raw, 0.0).label("avg_rating")
    
    # Normalizatsiya uchun max_views subquery (DB katta bo'lsa buni keshdan olish tavsiya etiladi)
    max_views_sq = select(func.max(Anime.views_week)).scalar_subquery()
    
    # Normalizatsiyalangan Score formulasi (0.0 dan 1.0 gacha skala)
    norm_views = cast(Anime.views_week, Float) / func.nullif(max_views_sq, 0)
    norm_rating = cast(avg_rating, Float) / 5.0
    
    score_formula = (func.coalesce(norm_views, 0.0) * 0.7) + (norm_rating * 0.3)
    score = score_formula.label("score")

    # 2. Queryni shakllantirish
    stmt = (
        select(
            Anime.anime_id,
            Anime.title,
            Anime.views_week,
            avg_rating,
            score
        )
        .order_by(desc(score))
        .limit(10)
    )

    # 3. Ma'lumotlarni olish
    top_animes = (await session.execute(stmt)).all()

    if not top_animes:
        return await callback.answer("Hozircha reyting ma'lumotlari yo'q.", show_alert=True)

    # 4. Matnni shakllantirish (UX Pro)
    text = "🏆 <b>HAFTALIK TOP ANIMELAR</b>\n"
    text += "━━━━━━━━━━━━━━\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, row in enumerate(top_animes, 1):
        # Trending logikasi: Haqiqiy ommaboplikka qarab
        prefix = "🔥 <b>TRENDING</b>\n" if row.views_week > 1000 else ""
        medal = medals[i-1] if i <= 3 else f"<b>{i}.</b>"
        
        # Title uzunligini cheklash
        clean_title = row.title[:40] + "..." if len(row.title) > 40 else row.title
        
        # Raqamlarni chiroyli formatlash
        formatted_views = f"{row.views_week:,}".replace(",", " ")
        rating = round(float(row.avg_rating), 1)
        
        # Dinamik reyting emojisi
        if rating >= 4.5:
            star = "🌟"
        elif rating >= 3.0:
            star = "⭐"
        else:
            star = "➖"
        
        text += (
            f"{prefix}{medal} <b>{clean_title}</b>\n"
            f"   {star} {rating}   |   👁 {formatted_views}\n\n"
        )

    # 5. Tugmalar
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"🔄 Yangilash ({len(top_animes)})", callback_data="Anime_ranked")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="reyting_menu")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    
    await callback.answer()

