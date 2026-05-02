

from aiogram import Router, types, F
router = Router()


from aiogram import types, Router, F
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
import logging

from database.models import DBUser, Anime, History, Favorite, Comment

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

        await callback.answer("📊 Deep analytics yuklanmoqda...")

        now = datetime.now(timezone.utc)

        day_7 = now - timedelta(days=7)
        day_30 = now - timedelta(days=30)

        # ================= USER GROWTH TREND =================
        users_7d = await session.scalar(
            select(func.count(DBUser.user_id))
            .where(DBUser.joined_at >= day_7)
        )

        users_30d = await session.scalar(
            select(func.count(DBUser.user_id))
            .where(DBUser.joined_at >= day_30)
        )

        total_users = await session.scalar(
            select(func.count(DBUser.user_id))
        )

        # growth rate (oddiy formula)
        growth_rate = round((users_7d / users_30d) * 100, 2) if users_30d else 0

        # ================= ENGAGEMENT =================
        total_watch = await session.scalar(
            select(func.count(History.id))
        )

        total_fav = await session.scalar(
            select(func.count(Favorite.user_id))
        )

        total_comments = await session.scalar(
            select(func.count(Comment.id))
        )

        engagement_rate = round((total_watch + total_fav + total_comments) / max(total_users, 1), 2)

        # ================= CONTENT PERFORMANCE =================
        top_anime_views = await session.scalar(
            select(func.max(Anime.views_week))
        ) or 0

        avg_views = await session.scalar(
            select(func.avg(Anime.views_week))
        ) or 0

        # ================= RETENTION (SIMPLE MODEL) =================
        active_7d = await session.scalar(
            select(func.count(func.distinct(History.user_id)))
            .where(History.watched_at >= day_7)
        )

        retention = round((active_7d / max(total_users, 1)) * 100, 2)

        # ================= UX DASHBOARD =================
        text = (
            "📊 <b>DEEP ANALYTICS DASHBOARD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "👥 <b>User Growth</b>\n"
            f"• Total users: <b>{total_users}</b>\n"
            f"• Last 7 days: <b>{users_7d}</b>\n"
            f"• Last 30 days: <b>{users_30d}</b>\n"
            f"• Growth rate: <b>{growth_rate}%</b>\n\n"

            "📈 <b>Engagement</b>\n"
            f"• Watch actions: <b>{total_watch}</b>\n"
            f"• Favorites: <b>{total_fav}</b>\n"
            f"• Comments: <b>{total_comments}</b>\n"
            f"• Engagement/user: <b>{engagement_rate}</b>\n\n"

            "🎬 <b>Content Performance</b>\n"
            f"• Top views: <b>{top_anime_views}</b>\n"
            f"• Avg views: <b>{round(avg_views, 2)}</b>\n\n"

            "🔁 <b>Retention</b>\n"
            f"• 7-day active users: <b>{active_7d}</b>\n"
            f"• Retention rate: <b>{retention}%</b>\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ Updated: <code>{now.strftime('%Y-%m-%d %H:%M:%S')}</code>"
        )

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔄 Refresh",
                    callback_data="admin_deep_stats"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="admin_panel"
                )
            ]
        ])

        await callback.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Deep stats error: {e}", exc_info=True)
        await callback.answer("⚠️ Deep analytics xatosi", show_alert=True)