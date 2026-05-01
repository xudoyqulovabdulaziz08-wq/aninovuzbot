# handlers/admin.py
import datetime
import logging
from aiogram import Router, types, F
import pytz
from database.models import DBUser, Channel
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from keyboards.inline import admin_panel_kb, creator_panel_kb
from datetime import datetime

# Dispatcher o'rniga Router ishlatamiz
router = Router()

# Creator ID ni config'dan olamiz
CREATOR_ID = config.CREATOR_ID

# ================= creator panel =================
@router.message(F.text == "👑 CREATOR PANEL")
async def creator_panel(message: types.Message):
    # ID bo'yicha qat'iy tekshiruv
    if message.from_user.id != CREATOR_ID:
        return await message.answer("❌ Bu bo'lim faqat bot egasi uchun!")
    
    await message.answer(
        "👑 <b>ASOSIY CREATOR BOSHQARUV PANELI</b>\n\n"
        "• Barcha adminlarni boshqarish\n"
        "• To'liq statistika\n"
        "• Bazani tahrirlash\n\n"
        "<i>Sizning huquqlaringiz cheksiz.</i>" ,
        reply_markup=creator_panel_kb(Creator_ID=message.from_user.id),
        parse_mode="HTML"
    )
    

# ================= admin panel =================

@router.message(F.text == "⚙️ SC ADMIN PANEL")
async def admin_panel(message: types.Message, user: DBUser, session: AsyncSession):
    # Xavfsizlik tekshiruvi: Faqat Creator yoki Admin kira oladi
    if message.from_user.id == config.CREATOR_ID or user.status == "admin":
        uzb_tz = pytz.timezone('Asia/Tashkent')
        now = datetime.now(uzb_tz)
        
        text = (
            f"⚙️ <b>ANI NOWUZ | BOSHQARUV PANELI</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Admin:</b> {message.from_user.mention_html()}\n"
            f"📅 <b>Sana:</b> {now.strftime('%d.%m.%Y | %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Tezkor ko'rsatkichlar:</b>\n"
            f"• Tizim: 🟢 Ishchi holatda\n"
            f"• DB Latency: Minimal\n\n"
            f"👇 <i>Kerakli bo'limni tanlang:</i>"
        )
        
        # Klaviaturaga user_id va statusni uzatamiz
        kb = admin_panel_kb(user_id=message.from_user.id, user_status=user.status)
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        # Oddiy user kirmoqchi bo'lsa javob bermaslik yoki xato deyish
        await message.answer("⚠️ Kechirasiz, bu bo'limga kirish huquqingiz yo'q.")







