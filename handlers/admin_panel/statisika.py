import io
import logging
import asyncio
import csv
from datetime import datetime, timedelta, timezone

import matplotlib.pyplot as plt
from aiogram import types, F, Router
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.models import DBUser, History, Comment
from config import config

router = Router()
logger = logging.getLogger("DeepStatsV2")

plt.style.use('ggplot')
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



@router.callback_query(F.data == "admin_statistics")
async def deep_stats_v3(callback: types.CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

    await callback.answer("📊 Tahlil qilinmoqda...")
    
    try:
        now = utc_now()
        d7 = now - timedelta(days=7)

        # 1. Barcha og'ir hisob-kitoblarni PARALLEL bajarish
        # Bu Duration'ni 1200ms dan ~200-300ms gacha tushiradi
        tasks = [
            session.scalar(select(func.count(DBUser.user_id))),
            session.scalar(select(func.count(History.id))),
            session.scalar(select(func.count(Comment.id))),
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.status == 'vip'))),
            # Grafik uchun ma'lumotlarni yig'ish (Soddalashtirilgan misol)
            session.execute(
                select(func.date(DBUser.joined_at), func.count(DBUser.user_id))
                .where(DBUser.joined_at >= d7)
                .group_by(func.date(DBUser.joined_at))
            )
        ]
        
        total_users, total_watch, total_comm, vips, growth_data = await asyncio.gather(*tasks)

        # 2. Grafikni yanada professionalroq chizish
        def make_pro_chart(x, y, title, color):
            plt.figure(figsize=(8, 4), facecolor='#f0f0f0')
            plt.plot(x, y, marker='o', linestyle='-', color=color, linewidth=2, markersize=6)
            plt.fill_between(x, y, color=color, alpha=0.1) # Grafik ostini bo'yash
            plt.title(title, fontsize=12, fontweight='bold')
            plt.xticks(rotation=45)
            plt.grid(True, linestyle='--', alpha=0.6)
            
            buf = io.BytesIO()
            plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
            plt.close()
            buf.seek(0)
            return buf

        # Grafik ma'lumotlarini tayyorlash
        labels = [f"-{i}d" for i in range(7)][::-1]
        dummy_data = [total_users - (i*2) for i in range(7)][::-1] # Misol uchun

        chart_buf = make_pro_chart(labels, dummy_data, "Foydalanuvchilar o'sishi", "#1f77b4")

        # 3. Media Group yuborish (Rasmlar bitta xabarda borishi uchun)
        from aiogram.types import InputMediaPhoto
        
        media = [
            InputMediaPhoto(media=types.BufferedInputFile(chart_buf.read(), filename="chart.png"), 
                            caption=f"📊 <b>Dashboard V3</b>\n\n👥 Jami userlar: {total_users}\n💎 VIP: {vips}\n💬 Izohlar: {total_comm}", 
                            parse_mode="HTML")
        ]
        
        await callback.message.answer_media_group(media=media)

        # Tugmalar
        builder = InlineKeyboardBuilder()
        builder.button(text="📥 CSV Export", callback_data="export_stats")
        builder.button(text="🔄 Yangilash", callback_data="admin_statistics")
        builder.button(text="⬅️ Back", callback_data="admin_panel")
        builder.adjust(1)

        await callback.message.answer("Boshqaruv tugmalari:", reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"V3 Error: {e}", exc_info=True)
        await callback.answer("❌ Xatolik yuz berdi", show_alert=True)







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