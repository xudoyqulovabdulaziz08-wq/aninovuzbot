import pytz
import logging
from datetime import datetime, timezone
from aiogram import types, F, Router
from typing import Any, Union  # ✅ To'g'risi shu
from sqlalchemy import select, desc, func, cast, Float, case
from database.models import DBUser, Anime
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
from database.cache import valkey
from aiogram.exceptions import TelegramBadRequest
from html import escape
router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)



#======== reyting_menu =========

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





@router.callback_query(F.data == "User_ranked")
async def user_rank(callback: types.CallbackQuery, session: AsyncSession = None):
    # 1. Session himoyasi (Middleware None qaytarsa)
    if session is None:
        return await callback.answer(
            "⚠️ Ma'lumotlar bazasi vaqtincha ishlamayapti.\nIltimos, birozdan so'ng urinib ko'ring.", 
            show_alert=True
        )

    try:
        # 2. Asosiy Reyting Algoritmi (Top 10)
        # log() va max() OVER() faqat SELECT ichida ishlatiladi
        log_p = func.ln(func.coalesce(DBUser.points, 0) + 1)
        log_r = func.ln(func.coalesce(DBUser.referral_count, 0) + 1)
        
        score_f = (
            (log_p / func.nullif(func.max(log_p).over(), 0) * 0.7) +
            (log_r / func.nullif(func.max(log_r).over(), 0) * 0.3)
        )
        score_label = score_f.label("score")

        stmt = (
            select(
                DBUser.user_id,
                DBUser.username,
                DBUser.points,
                DBUser.referral_count,
                DBUser.status,
                score_label
            )
            .order_by(desc("score"))
            .limit(10)
        )
        
        result = await session.execute(stmt)
        top_users = result.fetchall()

        if not top_users:
            return await callback.answer("Hozircha reyting ma'lumotlari yo'q.", show_alert=True)

        # 3. Foydalanuvchi o'rnini hisoblash (Xavfsiz usul - Window function'siz)
        user_data_stmt = select(DBUser.points, DBUser.referral_count).where(DBUser.user_id == callback.from_user.id)
        u_res = (await session.execute(user_data_stmt)).fetchone()
        
        user_rank_val = "1000+"
        if u_res:
            # Oddiy ballar bo'yicha hisoblash bazaga yuklama bermaydi
            rank_stmt = select(func.count()).select_from(DBUser).where(
                (DBUser.points > u_res.points) | 
                ((DBUser.points == u_res.points) & (DBUser.referral_count > u_res.referral_count))
            )
            user_rank_val = (await session.execute(rank_stmt)).scalar() + 1

        # 4. Matn shakllantirish
        text = "🏆 <b>TOP FOYDALANUVCHILAR</b>\n"
        text += "━━━━━━━━━━━━━━\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        user_in_top = False
        
        for i, row in enumerate(top_users, 1):
            if row.user_id == callback.from_user.id:
                user_in_top = True
            
            medal = medals[i-1] if i <= 3 else f"<b>{i}.</b>"
            safe_name = f"@{escape(row.username)}" if row.username else f"<code>ID:{row.user_id}</code>"
            vip_badge = "✨ " if row.status == "vip" else ""
            fmt_points = f"{row.points:,}".replace(",", " ")
            
            line = f"<u>{vip_badge}{safe_name}</u>" if row.user_id == callback.from_user.id else f"{vip_badge}{safe_name}"
            text += f"{medal} {line}\n   💰 {fmt_points} ball | 👥 {row.referral_count} ta\n\n"

        if not user_in_top:
            text += "━━━━━━━━━━━━━━\n"
            text += f"👤 Siz: <b>{user_rank_val}-o'rinda</b>\n"

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="User_ranked")],
            [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="reyting_menu")]
        ])

        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    except Exception as e:
        print(f"Reyting xatosi: {e}")
        await callback.answer("❌ Ma'lumotlarni yuklashda xatolik yuz berdi.", show_alert=True)
    
    await callback.answer()

