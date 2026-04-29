# handlers/admin.py
import datetime
import logging
from aiogram import Router, types, F
from database.models import DBUser
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from keyboards.inline import admin_panel_kb, creator_panel_kb

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
    if message.from_user.id == config.CREATOR_ID or user.status == "admin":
        # Bazadan tezkor statistika olish (ixtiyoriy)
        # total_users = await session.scalar(select(func.count(DBUser.id)))
        
        text = (
            f"⚙️ <b>ANI NOWUZ | BOSHQARUV PANELI</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Admin:</b> {message.from_user.mention_html()}\n"
            f"📅 <b>Sana:</b> {datetime.now().strftime('%d.%m.%Y | %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Tezkor ko'rsatkichlar:</b>\n"
            f"• Tizim: 🟢 Ishchi holatda\n"
            f"• DB Latency: Minimal\n\n"
            f"👇 <i>Kerakli bo'limni tanlang:</i>"
        )
        
        await message.answer(
            text,
            reply_markup=admin_panel_kb(is_admin=True),
            parse_mode="HTML"
        )