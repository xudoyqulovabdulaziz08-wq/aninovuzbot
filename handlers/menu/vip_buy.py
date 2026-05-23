import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from database.repository import UserRepository
from keyboards.inline import get_vip_kb

router = Router(name="vip_router")
logger = logging.getLogger(__name__)


@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu")
async def buy_vip_menu(event: types.Message | types.CallbackQuery, state: FSMContext, session: AsyncSession, user: dict):
    # 'user' - bu middleware orqali kelayotgan keshdagi ma'lumot
    # user['is_vip'] - bazadagi logic asosida avtomatik keladi
    
    is_vip = user.get("is_vip", False)
    points = user.get("points", 0)
    
    status_info = "👑 <b>Status:</b> VIP" if is_vip else "👤 <b>Status:</b> Oddiy foydalanuvchi"
    
    text = (
        "💎 <b>VIP PREMIYUM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_info}\n"
        f"💰 Balans: <b>{points} ball</b>\n\n"
        "✨ <b>VIP imkoniyatlari:</b>\n"
        "🚀 <b>Yuqori tezlik:</b> Kontentga cheksiz kirish\n"
        "🚫 <b>Reklamasiz:</b> Hech qanday ortiqcha xabarlarsiz\n"
        "📂 <b>Eksklyuziv:</b> Faqat VIP uchun maxsus kanallar\n"
        "👑 <b>Status:</b> Ismingiz yonida maxsus belgi\n\n"
        "🏷 <b>Tarif:</b> <code>100 ball = 30 kun</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 VIP faollashtirish uchun tugmani bosing:"
    )
    
    kb = get_vip_kb(is_vip=is_vip) # Klaviatura statusga qarab o'zgarishi mumkin
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer()
        await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")