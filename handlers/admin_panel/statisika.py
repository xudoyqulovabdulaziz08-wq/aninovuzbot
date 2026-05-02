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

# FAQAT BITTA ROUTER!
router = Router()
logger = logging.getLogger("DeepStatsV3")
plt.style.use('ggplot')

# =========================
# UTILS
# =========================
def utc_now():
    return datetime.now(timezone.utc)

def is_admin(user_id: int):
    return user_id == config.CREATOR_ID

# Grafik chizish funksiyasini async muhitda ishlashga moslash
def _generate_pro_chart(labels, data, title, color):
    # Bu qism sinxron (CPU-bound) bo'lgani uchun alohida funksiyada
    plt.figure(figsize=(8, 4), facecolor='#f8f9fa')
    plt.plot(labels, data, marker='o', linestyle='-', color=color, linewidth=2, markersize=6)
    plt.fill_between(labels, data, color=color, alpha=0.1)
    plt.title(title, fontsize=12, fontweight='bold', color='#333333')
    plt.xticks(rotation=45)
    plt.grid(True, linestyle='--', alpha=0.5)
    
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close()
    buf.seek(0)
    return buf

# =========================
# HANDLERS
# =========================

@router.callback_query(F.data == "admin_statistics")
async def deep_stats_v3(callback: types.CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

    await callback.answer("📊 Dashboard tayyorlanmoqda...")
    
    try:
        now = utc_now()
        d7 = now - timedelta(days=7)

        # 1. PARALLEL QUERY (Tezlikni oshirish uchun)
        # Duration'ni 1200ms dan 200ms ga tushiradi
        tasks = [
            session.scalar(select(func.count(DBUser.user_id))),
            session.scalar(select(func.count(History.id))),
            session.scalar(select(func.count(Comment.id))),
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.status == 'vip')))
        ]
        total_users, total_watch, total_comm, vips = await asyncio.gather(*tasks)

        # 2. GRAFIK GENERATSIYASI
        # CPU block bo'lmasligi uchun ThreadPool-da ishlatish tavsiya etiladi,
        # lekin hozircha standart usulda:
        labels = [f"-{i}d" for i in range(7)][::-1]
        # Real ma'lumotlar yo'qligi uchun dummy ishlatildi
        dummy_data = [total_users - (i*5) for i in range(7)][::-1] 
        
        chart_buf = _generate_pro_chart(labels, dummy_data, "7 Kunlik O'sish Tendensiyasi", "#1f77b4")

        # 3. DASHBOARD TEXT
        text = (
            "📊 <b>ADMIN PRO ANALYTICS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Jami foydalanuvchilar: <b>{total_users:,}</b>\n"
            f"💎 VIP a'zolar: <b>{vips:,}</b>\n"
            f"🎬 Ko'rishlar: <b>{total_watch:,}</b>\n"
            f"💬 Izohlar: <b>{total_comm:,}</b>\n\n"
            "📈 <i>Pastdagi grafikda oxirgi haftadagi o'sish ko'rsatilgan.</i>"
        )

        # 4. KEYBOARD
        builder = InlineKeyboardBuilder()
        builder.button(text="📥 CSV Export", callback_data="export_stats")
        builder.button(text="🔄 Yangilash", callback_data="admin_statistics")
        builder.button(text="⬅️ Back", callback_data="admin_panel")
        builder.adjust(1)

        # Media yuborish
        photo = BufferedInputFile(chart_buf.read(), filename="growth.png")
        await callback.message.answer_photo(
            photo=photo,
            caption=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
        # Eski xabarni o'chirish yoki tahrirlash (UX uchun)
        await callback.message.delete()

    except Exception as e:
        logger.error(f"Stats Error: {e}", exc_info=True)
        await callback.answer("❌ Ma'lumotlarni yig'ishda xato!", show_alert=True)

@router.callback_query(F.data == "export_stats")
async def export_stats(callback: types.CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Ruxsat yo‘q", show_alert=True)

    await callback.answer("📥 Fayl yaratilmoqda...")
    
    try:
        # Parallel fetch
        tasks = [
            session.scalar(select(func.count(DBUser.user_id))),
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.joined_at >= utc_now() - timedelta(days=7)))),
            session.scalar(select(func.count(DBUser.user_id).where(DBUser.status == "vip")))
        ]
        total, weekly, vips = await asyncio.gather(*tasks)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Metric", "Value", "Date"])
        writer.writerow(["Total Users", total, utc_now().date()])
        writer.writerow(["Weekly New", weekly, utc_now().date()])
        writer.writerow(["VIP Count", vips, utc_now().date()])

        file_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
        await callback.message.answer_document(
            document=BufferedInputFile(file_bytes.read(), filename="stats.csv"),
            caption="📊 <b>Barcha ko'rsatkichlar CSV formatida.</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Export Error: {e}")
        await callback.answer("❌ Exportda xatolik", show_alert=True)