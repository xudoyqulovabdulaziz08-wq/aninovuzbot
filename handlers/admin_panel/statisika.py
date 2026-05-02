

from aiogram import Router, types, F
router = Router()


from aiogram import types, Router, F
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
import logging

from database.models import DBUser, Anime, History, Favorite, Comment, MODELS_TO_WATCH

router = Router()
logger = logging.getLogger("AdminDeepStats")


def is_admin(user_id: int) -> bool:
    from config import config
    return user_id == config.CREATOR_ID




@router.callback_query(F.data == "admin_statistics")
async def admin_deep_stats(callback: types.CallbackQuery, session: AsyncSession):
    try:
        if not is_admin(callback.from_user.id):
            return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

        await callback.answer("📊 Pro-tahlil tayyorlanmoqda...")

        now = datetime.now(timezone.utc)
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        # --- FOYDALANUVCHILAR TAHLILI ---
        # Bitta so'rovda bir nechta count'larni olish (Performance uchun)
        user_stmt = select(
            func.count(DBUser.user_id).label("total"),
            func.count(DBUser.user_id).filter(DBUser.joined_at >= d7).label("w_growth"),
            func.count(DBUser.user_id).filter(DBUser.joined_at >= d30).label("m_growth"),
            func.count(DBUser.user_id).filter(DBUser.status == "vip").label("vips")
        )
        u_res = await session.execute(user_stmt)
        u_stats = u_res.one()

        # --- FAOLLIK (ENGAGEMENT) ---
        act_stmt = select(
            func.count(History.id).label("watch_cnt"),
            func.count(Comment.id).label("comm_cnt"),
            func.count(func.distinct(History.user_id)).filter(History.watched_at >= d7).label("wau") # Weekly Active Users
        )
        a_res = await session.execute(act_stmt)
        a_stats = a_res.one()

        # --- MOLIYAVIY/BALLAR ANALITIKASI ---
        point_stats = await session.execute(select(
            func.sum(DBUser.points),
            func.avg(DBUser.points)
        ))
        total_p, avg_p = point_stats.one()

        # ================= HISOB-KITOB (PRO LOGIC) =================
        
        # 1. Growth Velocity (O'sish tezligi)
        # O'tgan haftadagi o'sishni foizda ko'rsatish
        velocity = round((u_stats.w_growth / max(u_stats.total, 1)) * 100, 1)

        # 2. Conversion (VIP ulushi)
        vip_conv = round((u_stats.vips / max(u_stats.total, 1)) * 100, 1)

        # 3. Stickiness Index (Foydalanuvchilarning botga "yopishib" qolishi)
        # WAU / Total Users
        stickiness = round((a_stats.wau / max(u_stats.total, 1)) * 100, 1)

        # ================= VIZUALIZATSIYA (UX) =================
        
        def get_trend_icon(val):
            return "📈" if val > 5 else "📉" if val < 2 else "📊"

        text = (
            "🚀 <b>SYSTEM PRO ANALYTICS</b>\n"
            f"📅 <code>{now.strftime('%d.%m.%Y | %H:%M')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "👥 <b>AUDITORIYA</b>\n"
            f"├ Jami: <b>{u_stats.total:,}</b>\n"
            f"├ Haftalik o'sish: <code>+{u_stats.w_growth}</code> ({velocity}%)\n"
            f"├ VIP konversiya: <b>{vip_conv}%</b>\n"
            f"└ Status: {get_trend_icon(velocity)}\n\n"

            "🎭 <b>KONTENT FAOLLIGI</b>\n"
            f"├ Ko'rilgan: <b>{a_stats.watch_cnt:,}</b>\n"
            f"├ Izohlar: <b>{a_stats.comm_cnt:,}</b>\n"
            f"├ 7-kunlik faollar (WAU): <b>{a_stats.wau:,}</b>\n"
            f"└ Stickiness: <b>{stickiness}%</b> " + ("🔥" if stickiness > 20 else "💤") + "\n\n"

            "💰 <b>EKONOMIKA (POINTS)</b>\n"
            f"├ Jami ballar: <b>{int(total_p or 0):,}</b>\n"
            f"└ O'rtacha/user: <b>{round(avg_p or 0, 1)}</b>\n\n"

            "⚙ <b>TEXNIK HOLAT</b>\n"
            f"├ Jami kanallar: <b>{len(MODELS_TO_WATCH)} modellar</b>\n"
            f"└ DB Timezone: <b>UTC+00</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Analitika har 15 daqiqada keshlanadi.</i>"
        )

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📥 To'liq hisobot (.csv)", callback_data="export_stats")],
            [types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_statistics")],
            [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")]
        ])

        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Stats Error: {e}")
        await callback.answer("❌ Ma'lumotlarni hisoblashda xatolik", show_alert=True)