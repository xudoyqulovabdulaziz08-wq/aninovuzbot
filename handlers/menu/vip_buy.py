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
from keyboards.inline import vip_buy_kb, buy_vip_med_kb

router = Router()
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
        status_info = "👑 <b>CREATOR</b>"
    elif user_status == "admin":
        status_info = "🛡 <b>ADMIN</b>"
    elif is_vip:
        status_info = "💎 <b>VIP</b>"
    else:
        status_info = "👤 <b>USER</b>"
    
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





@router.callback_query(F.data == "buy_vip_med")
async def buy_vip_med_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear() # Har doim yaxshi amaliyot
    VIP_PRICES = {
        "1m": "20,000",
        "3m": "55,000",
        "6m": "100,000",
        "12m": "180,000"
    }
    kb = buy_vip_med_kb(user_id=callback.from_user.id)
    text = (
        f"💎 <b>VIP SOTIB OLISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"VIP imkoniyatlarini ko'rib chiqing va o'zingizga mos tarifni tanlang.\n\n"
        f"💵 <b>VIP tarif narxlari:</b>\n"
        f"🚀 <b>1 oylik:</b> {VIP_PRICES['1m']} so'm\n"
        f"🚀 <b>3 oylik:</b> {VIP_PRICES['3m']} so'm\n"
        f"🚀 <b>6 oylik:</b> {VIP_PRICES['6m']} so'm\n"
        f"🚀 <b>1 yillik:</b> {VIP_PRICES['12m']} so'm\n\n"
        f"🏷 <b>Bonus:</b> <code>100 ball = 30 kun</code>\n"
        f"👇 VIP faollashtirish uchun admin bilan bog'laning:"
    )
    
    kb = buy_vip_med_kb()
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ VIP menyu xatosi: {e}")
            
    # Answer har doim chaqirilishi kerak
    await callback.answer("💎 VIP sotib olish menyusi yuklandi")