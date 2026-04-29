# handlers/admin.py
import logging
from aiogram import Router, types, F
from database.models import DBUser
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from keyboards.inline import admin_panel_kb, creator_panel_kb
from handlers.user import Creator_ID
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
from sqlalchemy.ext.asyncio import AsyncSession

@router.message(F.text == "⚙️ SC ADMIN PANEL")
async def admin_panel(message: types.Message, user: DBUser, session: AsyncSession): # <-- session qo'shildi
    
    # Creator yoki Admin ekanligini tekshiramiz
    # Tavsiya: config.CREATOR_ID ni ishlating
    if message.from_user.id == config.CREATOR_ID or user.status == "admin":
        await message.answer(
            "⚙️ <b>Admin panel</b>\n\n"
            "• Foydalanuvchilar ro'yxati\n"
            "• Reklama yuborish\n"
            "• Statistika",
         
            reply_markup=admin_panel_kb(is_admin=user.status == "admin"),
            parse_mode="HTML"
        )
        
    else:
        await message.answer("❌ Ruxsat yo'q! Bu bo'lim faqat adminlar uchun.")