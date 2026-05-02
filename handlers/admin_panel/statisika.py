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
from aiogram.types import InputMediaPhoto, BufferedInputFile

from database.models import DBUser, History, Comment
from config import config

# 1. Yagona Router (Not Handled xatosini yo'qotish uchun)
router = Router()
logger = logging.getLogger("DeepStatsV3")

# Grafik dizayni
plt.style.use('ggplot')

# =========================
# UTILS
# =========================

def utc_now():
    """Hozirgi vaqtni UTCda qaytaradi"""
    return datetime.now(timezone.utc)


def is_admin(user_id: int):
    """Admin ekanligini tekshirish"""
    return user_id == config.CREATOR_ID


def generate_chart_image(labels, values, title, color="#1f77b4"):
    """Sinxron grafik chizish funksiyasi"""
    plt.figure(figsize=(8, 4), facecolor='#f8f9fa')
    plt.plot(labels, values, marker='o', linestyle='-', color=color, linewidth=2, markersize=6)
    plt.fill_between(labels, values, color=color, alpha=0.1)
    
    plt.title(title, fontsize=12, fontweight='bold', color='#333333')
    plt.xticks(rotation=45)
    plt.grid(True, linestyle='--', alpha=0.5)
    
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close()
    buf.seek(0)
    return buf


# =========================
# MAIN DASHBOARD HANDLER
# =========================

@router.callback_query(F.data == "admin_statistics")
async def admin_deep_stats(callback: types.CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

    await callback.answer("📊 Analytics Dashboard yuklanmoqda...")
    
    try:
        now = utc_now()
        d7 = now - timedelta(days=7)

        # 1. PARALLEL QUERY (Tezlik uchun - Durationni kamaytiradi)
        tasks = [
            session.scalar(select(func.count(DBUser.user_id))), # Jami userlar
            session.scalar(select(func.count(History.id))),    # Jami ko'rishlar
            session.scalar(select(func.count(Comment.id))),    # Jami izohlar
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.status == 'vip'))), # VIPlar
            # Haftalik trend uchun ma'lumot (Group by date)
            session.execute(
                select(func.date(DBUser.joined_at), func.count(DBUser.user_id))
                .where(DBUser.joined_at >= d7)
                .group_by(func.date(DBUser.joined_at))
                .order_by(func.date(DBUser.joined_at))
            )
        ]
        
        total_users, total_watch, total_comm, vips, growth_res = await asyncio.gather(*tasks)
        
        # Grafik ma'lumotlarini tayyorlash
        growth_data = {str(r[0]): r[1] for r in growth_res.all()}
        labels = []
        values = []
        
        for i in range(6, -1, -1):
            day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            labels.append(day[-5:]) # MM-DD formati
            values.append(growth_data.get(day, 0))

        # 2. GRAFIK CHIZISH
        chart_buf = generate_chart_image(labels, values, "Oxirgi 7 kunlik o'sish", "#2ecc71")

        # 3. KPI CALCULATIONS
        retention = round((values[-1] / max(total_users, 1)) * 100, 1)

        # 4. DASHBOARD TEXT
        text = (
            "🚀 <b>DEEP ANALYTICS DASHBOARD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👥 <b>FOYDALANUVCHILAR</b>\n"
            f"├ Jami: <b>{total_users:,}</b>\n"
            f"├ VIP: <b>{vips:,}</b>\n"
            f"└ Bugun: <b>+{values[-1]} yangi</b>\n\n"
            
            "🎬 <b>FAOLLIK</b>\n"
            f"├ Ko'rishlar: <b>{total_watch:,}</b>\n"
            f"├ Izohlar: <b>{total_comm:,}</b>\n"
            f"└ Retention: <b>{retention}%</b>\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <i>Yangilandi: {now.strftime('%H:%M:%S')} UTC</i>"
        )

        # 5. KEYBOARD
        kb = InlineKeyboardBuilder()
        kb.button(text="📥 CSV Export", callback_data="export_stats")
        kb.button(text="🔄 Yangilash", callback_data="admin_statistics")
        kb.button(text="⬅️ Back", callback_data="admin_panel")
        kb.adjust(1)

        # Rasm yuborish
        photo = BufferedInputFile(chart_buf.read(), filename="stats.png")
        
        # UX: Agar rasm bo'lsa, yangisini yuborib eskisini o'chiramiz
        await callback.message.answer_photo(
            photo=photo,
            caption=text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        await callback.message.delete()

    except Exception as e:
        logger.error(f"DeepStats Error: {e}", exc_info=True)
        await callback.answer("❌ Analytics tizimida xatolik!", show_alert=True)


# =========================
# EXPORT HANDLER
# =========================

@router.callback_query(F.data == "export_stats")
async def export_stats(callback: types.CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

    await callback.answer("📥 Export tayyorlanmoqda...")
    
    try:
        now = utc_now()
        d7 = now - timedelta(days=7)

        # Ma'lumotlarni yig'ish
        tasks = [
            session.scalar(select(func.count(DBUser.user_id))),
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.joined_at >= d7))),
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.status == "vip"))),
            session.scalar(select(func.count(History.id))),
            session.scalar(select(func.count(Comment.id)))
        ]
        total, weekly, vips, watches, comms = await asyncio.gather(*tasks)

        # CSV yaratish
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(["Hisobot turi", "Deep Analytics Export"])
        writer.writerow(["Sana", now.strftime("%Y-%m-%d %H:%M")])
        writer.writerow([])
        writer.writerow(["Ko'rsatkich", "Qiymat"])
        writer.writerow(["Jami foydalanuvchilar", total])
        writer.writerow(["Haftalik yangi userlar", weekly])
        writer.writerow(["VIP foydalanuvchilar", vips])
        writer.writerow(["Jami ko'rilgan animelar", watches])
        writer.writerow(["Jami qoldirilgan izohlar", comms])

        # Faylni yuborish
        file_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
        await callback.message.answer_document(
            document=BufferedInputFile(file_bytes.read(), filename=f"stats_{now.date()}.csv"),
            caption="📊 <b>Tizimning to'liq hisoboti (CSV)</b>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Export Error: {e}", exc_info=True)
        await callback.answer("❌ Export qilishda xatolik!", show_alert=True)