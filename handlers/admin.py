# handlers/admin.py
import datetime
import logging
from aiogram import Router, types, F
import pytz
from database.models import DBUser, Channel
from aiogram.fsm.context import FSMContext
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from keyboards.inline import admin_panel_kb, creator_panel_kb
from datetime import datetime
from typing import Union
# Dispatcher o'rniga Router ishlatamiz
router = Router()

# Creator ID ni config'dan olamiz
CREATOR_ID = config.CREATOR_ID

# ================= creator panel =================
@router.message(F.text == "👑 CREATOR PANEL")
async def creator_panel(message: types.Message, state: FSMContext):
    await state.clear()
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



from aiogram.exceptions import TelegramBadRequest # Xatolikni tutib qolish uchun

@router.message(F.text == "⚙️ SC ADMIN PANEL")
@router.callback_query(F.data == "admin_panel")
async def admin_panel(event: Union[types.Message, types.CallbackQuery], user: DBUser, session: AsyncSession, state: FSMContext):
    await state.clear()
    
    is_callback = isinstance(event, types.CallbackQuery)
    user_id = event.from_user.id

    if user_id == config.CREATOR_ID or user.status == "admin":
        uzb_tz = pytz.timezone('Asia/Tashkent')
        now = datetime.now(uzb_tz)
        
        text = (
            f"⚙️ <b>ANI NOWUZ | BOSHQARUV PANELI</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Admin:</b> {event.from_user.mention_html()}\n"
            f"📅 <b>Sana:</b> {now.strftime('%d.%m.%Y | %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Tezkor ko'rsatkichlar:</b>\n"
            f"• Tizim: 🟢 Ishchi holatda\n"
            f"• DB Latency: Minimal\n\n"
            f"👇 <i>Kerakli bo'limni tanlang:</i>"
        )
        
        kb = admin_panel_kb(user_id=user_id, user_status=user.status)
        
        if is_callback:
            try:
                # 1. Avval tahrirlashga urinib ko'ramiz (agar eski xabar matn bo'lsa)
                await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except TelegramBadRequest:
                # 2. Agar eski xabar rasm bo'lsa (tahrirlab bo'lmasa), eskisini o'chirib yangisini yuboramiz
                await event.message.delete()
                await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
            
            await event.answer()
        else:
            # Matn yozilganda yangi xabar yuboramiz
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
            
    else:
        # Xavfsizlik uchun oddiy answer ishlatamiz
        msg = event.message if is_callback else event
        await msg.answer("⚠️ Kechirasiz, bu bo'limga kirish huquqingiz yo'q.")






