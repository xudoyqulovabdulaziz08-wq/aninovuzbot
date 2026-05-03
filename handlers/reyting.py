import pytz
import logging
import html
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
from database.connection import AsyncSessionLocal





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
async def anime_rank(callback: types.CallbackQuery, session: AsyncSession):
    """
    Anime reytingi: L2 kesh va optimallashgan DB hisob-kitobi[cite: 11, 16].
    """
    CACHE_KEY = "anime:top_ranking_v1"
    
    # 1. L2 KESHNI TEKSHIRISH[cite: 11]
    try:
        cached_data = await valkey.get("anime", "top_ranking_v1")
        if cached_data:
            return await render_ranking(callback, cached_data)
    except Exception as e:
        print(f"Cache Read Error: {e}") # Keshda xatolik bo'lsa DB ga o'tadi[cite: 18]

    # 2. DB'DAN HISOBLASH (Optimallashtirilgan formula)[cite: 12, 16, 17]
    try:
        # Reytingni hisoblash (0 ga bo'lishdan himoyalangan)
        avg_rating_raw = Anime.rating_sum / func.nullif(Anime.rating_count, 0)
        avg_rating = func.coalesce(avg_rating_raw, 0.0).label("avg_rating")
        
        # Max views subquery (Skalyar)
        max_views_sq = select(func.max(Anime.views_week)).scalar_subquery()
        
        # Ommaboplik formulasi: Views (70%) + Rating (30%)
        # Normalizatsiya: (current / max) * weight[cite: 16]
        norm_views = cast(Anime.views_week, Float) / func.nullif(max_views_sq, 0)
        norm_rating = cast(avg_rating, Float) / 5.0
        score = ((func.coalesce(norm_views, 0.0) * 0.7) + (func.coalesce(norm_rating, 0.0) * 0.3)).label("score")

        stmt = (
            select(Anime.title, Anime.views_week, avg_rating)
            .order_by(desc(score))
            .limit(10)
        )
        
        result = await session.execute(stmt)
        top_animes = [
            {
                "title": row.title,
                "views": row.views_week,
                "rating": round(float(row.avg_rating), 1)
            }
            for row in result.all()
        ]

        if not top_animes:
            return await callback.answer("📊 Hozircha ma'lumotlar yo'q...", show_alert=True)

        # 3. KESHGA YOZISH (10 daqiqa)[cite: 11]
        await valkey.set("anime", "top_ranking_v1", top_animes, ttl=600)
        await render_ranking(callback, top_animes)

    except Exception as e:
        print(f"Ranking System Error: {e}")
        await callback.answer("❌ Tizimda texnik nosozlik yuz berdi.", show_alert=True)

async def render_ranking(callback: types.CallbackQuery, data: List[Dict[str, Any]]):
    """
    Pro Max UX/UI: Chiroyli vizualizatsiya.
    """
    header = (
        "<b>🏆 HAFTALIK TREND ANIMELAR</b>\n"
        "<i>Eng ko'p ko'rilgan va yuqori baholangan</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    rows = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, anime in enumerate(data, 1):
        rank_icon = medals.get(i, f"<b>{i}.</b>")
        
        # Title qisqartirish
        title = anime["title"][:30] + ".." if len(anime["title"]) > 30 else anime["title"]
        
        # Vizual Reyting (Progress bar uslubida)
        stars_count = int(anime["rating"])
        progress = "🔹" * stars_count + "🔸" * (5 - stars_count)
        
        # Dinamik indikatorlar
        hot_label = "🔥" if anime["views"] > 5000 else "📈" if anime["views"] > 1000 else "✨"
        views_formatted = f"{anime['views']:,}".replace(",", " ")

        row = (
            f"{rank_icon} {hot_label} <b>{title}</b>\n"
            f"┣ {progress} <b>{anime['rating']}</b>\n"
            f"┗ 👁 {views_formatted} marta ko'rildi\n"
        )
        rows.append(row)

    footer = (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        "🕒 <i>Ma'lumotlar avtomatik yangilanadi.</i>"
    )

    text = header + "\n".join(rows) + footer

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="Anime_ranked")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="reyting_menu")]
    ])

    try:
        # Faqat o'zgarish bo'lsa xabar yangilanadi (Telegram xatoligini oldini olish)[cite: 18]
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    
    await callback.answer()









logger = logging.getLogger("UserRank")


#------------------------------------------------------------------------------------------

@router.callback_query(F.data == "User_ranked")
async def user_rank(callback: types.CallbackQuery, session: AsyncSession, user: dict = None):
    """
    Foydalanuvchilar reytingi: Logarifmik ball tizimi va dual-layer kesh[cite: 11, 15].
    """
    if not session:
        return await callback.answer("⚠️ Tizim vaqtincha band...", show_alert=True)

    CACHE_KEY = "users:top_10_ranking"
    user_id = callback.from_user.id
    
    try:
        # 1. L2 KESHNI TEKSHIRISH[cite: 11]
        top_users = await valkey.get("users", "top_10_ranking")
        
        if not top_users:
            # 2. MURAKKAB HISOBLASH (Faqat kesh bo'sh bo'lsa)[cite: 15, 18]
            # Logarifmik formula: Ballar (70%) va Referral (30%)
            log_p = func.ln(func.coalesce(DBUser.points, 0) + 1)
            log_r = func.ln(func.coalesce(DBUser.referral_count, 0) + 1)
            
            # Normalizatsiya subquery'lari
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
            top_users = [
                {
                    "user_id": r.user_id,
                    "username": r.username,
                    "points": r.points,
                    "refs": r.referral_count,
                    "status": r.status
                } for r in db_res.all()
            ]
            
            # Keshga yozish (15 daqiqa)
            if top_users:
                await valkey.set("users", "top_10_ranking", top_users, ttl=900)

        # 3. FOYDALANUVCHI O'RNINI ANIQLASH (Optimallashgan)
        my_rank = "1000+"
        in_top = next((i + 1 for i, u in enumerate(top_users) if u["user_id"] == user_id), None)
        
        if in_top:
            my_rank = in_top
        else:
            # Bazadan faqat o'rnini so'rash (Yengil query)
            my_pts = user.get("points", 0) if user else 0
            my_refs = user.get("referral_count", 0) if user else 0
            
            rank_stmt = select(func.count()).select_from(DBUser).where(
                or_(
                    DBUser.points > my_pts,
                    (DBUser.points == my_pts) & (DBUser.referral_count > my_refs)
                )
            )
            my_rank = (await session.execute(rank_stmt)).scalar() + 1

        await render_user_ranking(callback, top_users, my_rank, user_id)

    except Exception as e:
        print(f"User Ranking Error: {e}")
        await callback.answer("❌ Reytingni yuklashda xatolik yuz berdi.", show_alert=True)



#------------------------------------------------------------------------------------------------------------


async def render_user_ranking(callback: types.CallbackQuery, top_users: List[Dict], my_rank: Any, my_id: int):
    """
    Pro Max UX/UI: Elita foydalanuvchilar ko'rinishi.
    """
    header = (
        "<b>💎 ELITA FOYDALANUVCHILAR</b>\n"
        "<i>Eng faol va sodiq hamjamiyat a'zolari</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    rows = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, u in enumerate(top_users, 1):
        is_me = u["user_id"] == my_id
        rank_icon = medals.get(i, f"<b>{i}.</b>")
        
        # Username xavfsizligi
        name_raw = u['username'] if u['username'] else f"ID:{u['user_id']}"
        name = html.escape(name_raw)
        
        # VIP va o'zini ajratib ko'rsatish
        prefix = "⭐️ " if is_me else "💎 " if u["status"] == "vip" else "👤 "
        user_line = f"<u>{prefix}{name}</u>" if is_me else f"{prefix}{name}"
        
        points = f"{u['points']:,}".replace(",", " ")
        
        rows.append(
            f"{rank_icon} {user_line}\n"
            f"┣ 💰 <b>{points}</b> ball\n"
            f"┗ 👥 <b>{u['refs']}</b> referral\n"
        )

    footer = (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ Sizning o'rningiz: <b>#{my_rank}</b>\n"
        "🕒 <i>Reyting har 15 daqiqada yangilanadi.</i>"
    )

    text = header + "\n".join(rows) + footer

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="User_ranked")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="reyting_menu")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    
    await callback.answer()