import logging
from typing import Any
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from database.repository import UserRepository
from keyboards.inline import vip_buy_kb

router = Router(name="vip_router")
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')





#==========================💎 VIP sotib olish=============================#
#========================================================================#
@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu")
async def buy_vip_menu(event: types.Message | types.CallbackQuery, state: FSMContext, **data):
    await state.clear()
    user = data.get("user") or {}
    user_id = user.get("user_id") or event.from_user.id
    user_status = user.get("status", "user")
    is_vip = user.get("is_vip", False)
    
    points = user.get("points", 0)

    # 1. Creator tekshiruvi (config dan)
    if int(user_id) == int(CREATOR_ID):
        status_info = "👑 <b>Status:</b> Creator"
    
    # 2. Admin tekshiruvi (bazadagi status bo'yicha)
    elif user_status == "admin":
        status_info = "🛡 <b>Status:</b> Admin"
        
    # 3. VIP tekshiruvi
    elif is_vip:
        status_info = "💎 <b>Status:</b> VIP"
        
    # 4. Oddiy foydalanuvchi
    else:
        status_info = "👤 <b>Status:</b> Oddiy foydalanuvchi"
    
    text = (
        "💎 <b>VIP PREMIYUM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_info}\n"
        f"💰 Balans: <b>{points} ball</b>\n\n"
        "✨ <b>VIP imkoniyatlari:</b>\n"
        "🚀 <b>Yuqori tezlik:</b> Cheksiz kirish\n"
        "🚫 <b>Reklamasiz:</b> Toza kontent\n"
        "👑 <b>Status:</b> Maxsus belgi\n\n"
        "🏷 <b>Tarif:</b> <code>100 ball = 30 kun</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 VIP faollashtirish uchun tugmani bosing:"
    )
    
    kb = vip_buy_kb(is_vip=is_vip)
    
    # 4. XAVFSIZ JAVOB BERISH
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        # Callback holatida tugmani tahrirlash yoki yangi xabar yuborish
        await event.answer()
        await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")