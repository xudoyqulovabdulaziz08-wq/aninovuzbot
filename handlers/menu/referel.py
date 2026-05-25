import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from config import config

router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')





#========================creator_manage_admins===========================#
#========================================================================#
@router.callback_query(F.data == "")
async def buy_vip_bonus_handler(callback: types.CallbackQuery):
    
    text = (
        f"💫 <b>BALL BO'LIMI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Bu fuksiya tez orada qo'shiladi"
        f"❗️ Hozircha bu bo'limda bonus ballarni ko'rish imkoniyati mavjud emas, lekin tez orada qo'shiladi. Iltimos, yangilanishlarni kuting!"

    )
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet"),
        types.InlineKeyboardButton(text="💎 VIP  olish", callback_data="buy_vip_med")
    )

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"💫 BALL bo'limi xatosi: {e}")
    await callback.answer("💫 BALL bo'limi tez orada qo'shiladi")