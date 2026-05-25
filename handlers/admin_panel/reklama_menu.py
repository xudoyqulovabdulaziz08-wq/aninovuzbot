import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import admin_add_kb, admin_addert_kb

router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


#============================anime_add_menu==============================#
#========================================================================#
@router.callback_query(F.data == "admin_advertisement")
async def admin_add_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    text = (
        f"📣 <b>REKLAMA BO'LMI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Admin:</b> {callback.from_user.full_name}\n\n"
        f"Ushbu bo'lim orqali barcha foydalanuvchilarga xabar yoki reklama yuborishingiz mumkin.\n\n"
        f"⚠️ <i>Reklama yuborishdan oldin statistika bilan tanishib chiqing.</i>"
    )
    
    kb = admin_add_kb()

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Add  panel xatosi: {e}")
    finally:
        await callback.answer("📣 Reklama bo'limi")






#============================anime_add_menu==============================#
#========================================================================#
@router.callback_query(F.data == "admin_advert")
async def admin_addert_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    text = (
        f"📣 <b>REKLAMA REKLAMA YUBORISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Ushbu bo'lim orqali barcha foydalanuvchilarga xabar yoki reklama yuborishingiz mumkin.\n\n"
        f"⚠️ <i>Reklamani qanday yubormoqchisiz kerakli tugmani tanglang</i>"
    )

    kb = admin_addert_kb()


    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Bo'lim panel xatosi: {e}")
    finally:
        await callback.answer()
