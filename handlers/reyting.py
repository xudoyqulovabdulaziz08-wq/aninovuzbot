import pytz
import logging
from datetime import datetime, timezone
from aiogram import types, F, Router
from typing import Any, Union  # ✅ To'g'risi shu
from sqlalchemy import select, desc, func, cast, Float, case
from database.models import DBUser, Anime
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
from aiogram.fsm.context import FSMContext
from database.cache import valkey
from aiogram.exceptions import TelegramBadRequest
from html import escape
from typing import List, Dict, Any, Union
from sqlalchemy import select, func, desc, cast, Float, or_
from database.models import Anime
from database.connection import SafeSession




router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)



#======== reyting_menu =========


@router.message(F.text == "🌟 Reyting")
@router.callback_query(F.data == "reyting_menu")
async def ranked_full(event: Union[types.Message, types.CallbackQuery], state: FSMContext, user: dict = None):
    """
    Reyting menyusi: Keshdan foydalanadi va 0 ta DB query bilan ishlaydi.
    """
    await state.clear()
    
    is_callback = isinstance(event, types.CallbackQuery)
    message = event.message if is_callback else event

    if not message:
        return await event.answer("⚠️ Xatolik: Xabar topilmadi.") if is_callback else None

    # 1. PREMIUM UI DESIGN
    text = (
        "🌟 <b>REYTING BO'LIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang va eng yaxshilarni kashf eting: 🔍\n\n"
        "🎬 <b>Anime Reyting</b>\n"
        "└ <i>Eng ko'p ko'rilgan va ommabop animelar</i>\n\n"
        "🏆 <b>Top Foydalanuvchilar</b>\n"
        "└ <i>Eng faol va yuqori ballga ega userlar</i>\n\n"
        "🚀 <i>Yangi tizimlar ustida ish olib bormoqdamiz...</i>"
    )

    # VIP statusni keshdan tekshirish (Tezkor)
    if user and user.get("is_vip"):
        text += "\n\n✨ <b>Status:</b> 👑 VIP Foydalanuvchi"

    # 2. INTERACTIVE KEYBOARD
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🎬 Anime Reyting", callback_data="Anime_ranked"),
            types.InlineKeyboardButton(text="🏆 User Reyting", callback_data="User_ranked"),
        ]
        
    ])

    # 3. SECURE & FAST RESPONSE
    try:
        if is_callback:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await event.answer()
        else:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")

    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            if is_callback: await event.answer()
        elif "message can't be edited" in err_msg:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            # Kutilmagan xatoliklarni log qilish
            print(f"Reyting error: {e}")







@router.callback_query(F.data == "Anime_ranked")
async def anime_rank(callback: types.CallbackQuery, session: SafeSession):
    """
    Anime reytingi: Keshdan o'qiydi, agar yo'q bo'lsa DB'dan hisoblab keshga yozadi.[cite: 11, 16]
    """
    cache_key = "anime:top_ranking_v1"
    
    # 1. L2 KESHNI TEKSHIRISH[cite: 11]
    cached_data = await valkey.get("anime", "top_ranking_v1")
    
    if cached_data:
        # Keshdan olingan ma'lumotni render qilish
        return await render_ranking(callback, cached_data)

    # 2. DB'DAN HISOBLASH (Kesh bo'sh bo'lsa)[cite: 12, 16]
    try:
        avg_rating_raw = Anime.rating_sum / func.nullif(Anime.rating_count, 0)
        avg_rating = func.coalesce(avg_rating_raw, 0.0).label("avg_rating")
        
        max_views_sq = select(func.max(Anime.views_week)).scalar_subquery()
        
        # Ommaboplik formulasi (Views 70% + Rating 30%)
        norm_views = cast(Anime.views_week, Float) / func.nullif(max_views_sq, 0)
        norm_rating = cast(avg_rating, Float) / 5.0
        score = ((func.coalesce(norm_views, 0.0) * 0.7) + (norm_rating * 0.3)).label("score")

        stmt = (
            select(Anime.title, Anime.views_week, avg_rating)
            .order_by(desc(score))
            .limit(10)
        )
        
        result = await session.execute(stmt)
        top_animes = []
        
        for row in result.all():
            top_animes.append({
                "title": row.title,
                "views": row.views_week,
                "rating": round(float(row.avg_rating), 1)
            })

        if not top_animes:
            return await callback.answer("📊 Ma'lumotlar tayyorlanmoqda...", show_alert=True)

        # 3. KESHGA YOZISH (10 daqiqa muddatga)
        await valkey.set("anime", "top_ranking_v1", top_animes, ttl=600)
        
        await render_ranking(callback, top_animes)

    except Exception as e:
        print(f"Ranking error: {e}")
        await callback.answer("❌ Reytingni yuklashda xatolik.", show_alert=True)

async def render_ranking(callback: types.CallbackQuery, data: List[Dict[str, Any]]):
    """
    UX/UI qismi: Ma'lumotlarni chiroyli formatda ko'rsatish.
    """
    text = "🏆 <b>HAFTALIK TREND ANIMELAR</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, anime in enumerate(data, 1):
        medal = medals[i-1] if i <= 3 else f"<b>{i}.</b>"
        
        # Trending belgisi (Yuqori ko'rilgan bo'lsa)
        trend = "🔥 " if anime["views"] > 1000 else ""
        
        # Title uzunligini boshqarish
        title = anime["title"][:35] + "..." if len(anime["title"]) > 35 else anime["title"]
        
        # Reyting yulduzchasi
        star = "🌟" if anime["rating"] >= 4.5 else "⭐"
        views = f"{anime['views']:,}".replace(",", " ")

        text += (
            f"{medal} {trend}<b>{title}</b>\n"
            f"└ {star} {anime['rating']}  |  👁 {views}\n\n"
        )

    text += "🕒 <i>Reyting har 10 daqiqada yangilanadi.</i>"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="Anime_ranked")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="reyting_menu")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    
    await callback.answer()






from sqlalchemy import select, func, desc, or_


logger = logging.getLogger("UserRank")

@router.callback_query(F.data == "User_ranked")
async def user_rank(callback: types.CallbackQuery, session: SafeSession, user: dict = None):
    """
    Foydalanuvchilar reytingi: Logarifmik ball tizimi va L2 kesh bilan optimallashtirilgan.
    """
    if session is None:
        return await callback.answer("⚠️ Tizim vaqtincha band. Keyinroq urinib ko'ring.", show_alert=True)

    cache_key = "users:top_10_ranking"
    
    # 1. KESHNI TEKSHIRISH (Ultra-tezkor javob)[cite: 11]
    top_users_cached = await valkey.get("users", "top_10_ranking")
    
    try:
        if not top_users_cached:
            # 2. OG'IR HISOBLASH (Faqat kesh bo'sh bo'lsa bajariladi)[cite: 15]
            # Logarifmik formula: Ballar (70%) va Takliflar (30%) muvozanati
            log_p = func.ln(func.coalesce(DBUser.points, 0) + 1)
            log_r = func.ln(func.coalesce(DBUser.referral_count, 0) + 1)
            
            # Normalizatsiya uchun max qiymatlarni olish
            stmt_max = select(func.max(log_p), func.max(log_r))
            res_max = (await session.execute(stmt_max)).fetchone()
            max_p, max_r = (res_max[0] or 1), (res_max[1] or 1)

            score_f = (log_p / max_p * 0.7) + (log_r / max_r * 0.3)
            
            stmt = (
                select(DBUser.user_id, DBUser.username, DBUser.points, DBUser.referral_count, DBUser.status)
                .order_by(desc(score_f))
                .limit(10)
            )
            
            db_res = await session.execute(stmt)
            top_users_cached = [
                {
                    "user_id": r.user_id,
                    "username": r.username,
                    "points": r.points,
                    "refs": r.referral_count,
                    "status": r.status
                } for r in db_res.all()
            ]
            
            # Keshga 15 daqiqaga saqlash[cite: 18]
            if top_users_cached:
                await valkey.set("users", "top_10_ranking", top_users_cached, ttl=900)

        # 3. FOYDALANUVCHI O'RNINI ANIQLASH (Shaxsiy ma'lumot keshlanmaydi)
        user_id = callback.from_user.id
        rank_val = "1000+"
        
        # Agar user Top 10 ichida bo'lsa, count so'rovini yubormaymiz (Optimallashtirish)
        in_top = next((i + 1 for i, u in enumerate(top_users_cached) if u["user_id"] == user_id), None)
        
        if in_top:
            rank_val = in_top
        else:
            # Bazadan o'rnini hisoblash
            current_user_pts = user.get("points", 0) if user else 0
            rank_stmt = select(func.count()).select_from(DBUser).where(
                or_(
                    DBUser.points > current_user_pts,
                    (DBUser.points == current_user_pts) & (DBUser.referral_count > (user.get("referral_count", 0) if user else 0))
                )
            )
            rank_val = (await session.execute(rank_stmt)).scalar() + 1

        await render_user_ranking(callback, top_users_cached, rank_val, user_id)

    except Exception as e:
        logger.error(f"Ranking crash: {e}")
        await callback.answer("❌ Ma'lumotlarni yuklashda xatolik.", show_alert=True)

async def render_user_ranking(callback: types.CallbackQuery, top_users: List[Dict], my_rank: Any, my_id: int):
    """UX/UI qismi: Reytingni chiroyli formatda ko'rsatish."""
    text = "🏆 <b>ELITA FOYDALANUVCHILAR</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, u in enumerate(top_users, 1):
        is_me = u["user_id"] == my_id
        medal = medals[i-1] if i <= 3 else f"<b>{i}.</b>"
        
        # Xavfsizlik: Username'ni escape qilish
        name = f"@{escape(u['username'])}" if u["username"] else f"ID:{u['user_id']}"
        badge = "💎 " if u["status"] == "vip" else ""
        
        line = f"<u>{badge}{name}</u>" if is_me else f"{badge}{name}"
        points = f"{u['points']:,}".replace(",", " ")
        
        text += f"{medal} {line}\n└ 💰 <b>{points}</b> ball | 👥 <b>{u['refs']}</b> ref\n\n"

    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"👤 Sizning o'rningiz: <b>#{my_rank}</b>\n\n"
    text += "🕒 <i>Reyting har 15 daqiqada yangilanadi.</i>"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="User_ranked")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="reyting_menu")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()

