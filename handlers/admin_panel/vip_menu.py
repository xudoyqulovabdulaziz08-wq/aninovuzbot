import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import admin_vip_kb, admin_add_vip_kb


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


#==============================anime_menu================================#
#========================================================================#
@router.callback_query(F.data == "admin_vip_panel")
async def admin_vip_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    text = (
        f"💎 <b>VIP PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"VIP bo'limiga xush kelibsiz, <b>{callback.from_user.full_name}</b>!\n"
        f"Bu yerda VIP foydalanuvchilarni tayinlash  imkoniyatlar mavjud.\n"
        f"Kerakli bo'limni tanlang."
    )
    kb = admin_vip_kb

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Add  panel xatosi: {e}")
    finally:
        await callback.answer("💎 VIP panel yuklandi")



#==============================anime_menu================================#
#========================================================================#
@router.callback_query(F.data == "admin_add_vip")
async def admin_vip_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    text = (
        f"💎 <b>VIP FOYDALANUVCHI QO'SHISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"VIP foydalanuvchi qo'shish bo'limiga xush kelibsiz, <b>{callback.from_user.full_name}</b>!\n"
        f"Bu yerda foydalanuvchini VIP qilish uchun kerakli ma'lumotlarni kiriting."
    )
    kb = admin_add_vip_kb

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Add  panel xatosi: {e}")
    finally:
        await callback.answer("💎 VIP foydalanuvchi qo'shish paneli yuklandi")