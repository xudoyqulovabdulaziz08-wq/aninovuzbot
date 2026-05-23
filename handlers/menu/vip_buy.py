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


@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu")
async def buy_vip_menu(event: types.Message | types.CallbackQuery, state: FSMContext, **data):
    # 1. XAVFSIZ QO'LGA KIRITISH
    # Agar 'user' data ichida bo'lmasa yoki None bo'lsa, bo'sh lug'at {} qaytaradi.
    user = data.get("user") or {}
    
    # 2. XAVFSIZ MA'LUMOTLARNI O'QISH
    # .get() endi 'NoneType' xatosini bermaydi, chunki user hech qachon None emas
    is_vip = user.get("is_vip", False)
    points = user.get("points", 0)
    
    # 3. UI MANTIQI
    status_info = "👑 <b>Status:</b> VIP" if is_vip else "👤 <b>Status:</b> Oddiy foydalanuvchi"
    
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