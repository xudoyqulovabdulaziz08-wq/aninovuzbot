import logging
from aiogram import Router, types, F
from database.models import DBUser
from config import config

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
        "<i>Sizning huquqlaringiz cheksiz.</i>"
    )

# ================= admin panel =================
@router.message(F.text == "⚙️ SC ADMIN PANEL")
async def admin_panel(message: types.Message, user: DBUser):
    # Creator yoki Admin ekanligini tekshiramiz
    if message.from_user.id == CREATOR_ID or user.status == "admin":
        await message.answer(
            "⚙️ <b>Admin panel</b>\n\n"
            "• Foydalanuvchilar ro'yxati\n"
            "• Reklama yuborish\n"
            "• Statistika"
        )
    else:
        await message.answer("❌ Ruxsat yo'q!")