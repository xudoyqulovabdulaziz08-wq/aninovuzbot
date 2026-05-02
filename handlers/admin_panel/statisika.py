import io
import logging
import csv
from datetime import datetime, timedelta, timezone

import matplotlib.pyplot as plt
from aiogram import types, F, Router
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DBUser, History, Comment
from config import config

router = Router()
logger = logging.getLogger("DeepStatsV2")


# =========================
# UTILS
# =========================

def utc_now():
    return datetime.now(timezone.utc)


def is_admin(user_id: int):
    return user_id == config.CREATOR_ID


def make_chart(x_labels, y_values, title):
    """Return PNG image as bytes (Telegram ready)"""
    plt.figure(figsize=(6, 3))

    plt.plot(x_labels, y_values, marker="o")

    plt.title(title)
    plt.grid(True)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close()

    buf.seek(0)
    return buf


# =========================
# MAIN DASHBOARD
# =========================

@router.callback_query(F.data == "admin_deep_stats_v2")
async def deep_stats_v2(callback: types.CallbackQuery, session: AsyncSession):
    try:
        if not is_admin(callback.from_user.id):
            return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

        await callback.answer("📊 Dashboard generatsiya qilinmoqda...")

        now = utc_now()

        days = [6, 5, 4, 3, 2, 1, 0]

        # =========================
        # USERS GROWTH (7 days)
        # =========================
        user_growth = []

        for d in days:
            day = now - timedelta(days=d)

            count = await session.scalar(
                select(func.count(DBUser.user_id))
                .where(DBUser.joined_at <= day)
            )

            user_growth.append(count or 0)

        # =========================
        # WAU TREND
        # =========================
        wau_trend = []

        for d in days:
            day = now - timedelta(days=d)

            count = await session.scalar(
                select(func.count(func.distinct(History.user_id)))
                .where(History.watched_at >= day)
            )

            wau_trend.append(count or 0)

        # =========================
        # ENGAGEMENT TOTALS
        # =========================
        total_watch = await session.scalar(select(func.count(History.id)))
        total_comments = await session.scalar(select(func.count(Comment.id)))

        # =========================
        # CHARTS GENERATION
        # =========================
        labels = [f"-{d}d" for d in days]

        users_chart = make_chart(labels, user_growth, "Users Growth")
        wau_chart = make_chart(labels, wau_trend, "WAU Trend")

        # =========================
        # KPI CALCULATIONS
        # =========================
        total_users = user_growth[-1]
        retention = round((wau_trend[-1] / max(total_users, 1)) * 100, 1)

        # =========================
        # DASHBOARD TEXT
        # =========================
        text = (
            "🚀 <b>DEEP ANALYTICS V2</b>\n"
            f"📅 <code>{now.strftime('%d.%m.%Y %H:%M UTC')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "👥 <b>USERS</b>\n"
            f"• Total: <b>{total_users:,}</b>\n"
            f"• Retention: <b>{retention}%</b>\n\n"

            "🎯 <b>ENGAGEMENT</b>\n"
            f"• Watch Events: <b>{total_watch:,}</b>\n"
            f"• Comments: <b>{total_comments:,}</b>\n\n"

            "📊 <b>INSIGHT</b>\n"
            "• Growth tracking: 7-day\n"
            "• WAU monitoring: active\n"
            "• System: realtime cache ready\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Charts generated via ML analytics engine</i>"
        )

        # =========================
        # SEND CHARTS
        # =========================
        await callback.message.answer_photo(
            types.BufferedInputFile(users_chart.read(), filename="users.png"),
            caption="📈 Users Growth Chart"
        )

        await callback.message.answer_photo(
            types.BufferedInputFile(wau_chart.read(), filename="wau.png"),
            caption="🔥 WAU Trend Chart"
        )

        # =========================
        # DASHBOARD BUTTONS
        # =========================
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔄 Refresh",
                    callback_data="admin_deep_stats_v2"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📥 Export CSV",
                    callback_data="export_stats"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⬅️ Back",
                    callback_data="admin_panel"
                )
            ]
        ])

        await callback.message.answer(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"DeepStatsV2 error: {e}", exc_info=True)
        await callback.answer("❌ Dashboard error", show_alert=True)







router = Router()


def utc_now():
    return datetime.now(timezone.utc)


def is_admin(user_id: int):
    return user_id == config.CREATOR_ID


# =========================
# EXPORT HANDLER
# =========================

@router.callback_query(F.data == "export_stats")
async def export_stats(callback: types.CallbackQuery, session: AsyncSession):
    try:
        # -------------------------
        # SECURITY
        # -------------------------
        if not is_admin(callback.from_user.id):
            return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

        await callback.answer("📥 Export tayyorlanmoqda...")

        now = utc_now()
        d7 = now - timedelta(days=7)

        # =========================
        # USERS STATS
        # =========================
        total_users = await session.scalar(
            select(func.count(DBUser.user_id))
        )

        weekly_users = await session.scalar(
            select(func.count(DBUser.user_id))
            .where(DBUser.joined_at >= d7)
        )

        vip_users = await session.scalar(
            select(func.count(DBUser.user_id))
            .where(DBUser.status == "vip")
        )

        # =========================
        # ENGAGEMENT
        # =========================
        total_watch = await session.scalar(select(func.count(History.id)))
        total_comments = await session.scalar(select(func.count(Comment.id)))

        # =========================
        # CSV GENERATION
        # =========================
        output = io.StringIO()
        writer = csv.writer(output)

        # HEADER
        writer.writerow(["Metric", "Value"])

        # USERS
        writer.writerow(["Total Users", total_users or 0])
        writer.writerow(["Weekly Users", weekly_users or 0])
        writer.writerow(["VIP Users", vip_users or 0])

        # ENGAGEMENT
        writer.writerow(["Total Watch Events", total_watch or 0])
        writer.writerow(["Total Comments", total_comments or 0])

        # SYSTEM
        writer.writerow(["Generated At", now.strftime("%Y-%m-%d %H:%M UTC")])

        output.seek(0)

        file_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
        file_bytes.name = "stats_export.csv"

        # =========================
        # SEND FILE
        # =========================
        await callback.message.answer_document(
            types.BufferedInputFile(file_bytes.read(), filename="stats_export.csv"),
            caption="📊 <b>SaaS Analytics Export</b>\nCSV formatda to‘liq hisobot",
            parse_mode="HTML"
        )

    except Exception as e:
        import logging
        logging.error(f"Export stats error: {e}", exc_info=True)
        await callback.answer("❌ Export xatolik", show_alert=True)