import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from keyboards.inline import admin_panel_kb, creator_panel_kb
from    config import config

router = Router()
logger = logging.getLogger(__name__)





#==========================⚙️ SC ADMIN PANEL============================#
#========================================================================#
@router.message(F.text == "⚙️ SC ADMIN PANEL")
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(event: types.Message | types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    # Statusni tekshirish logikangizni shu yerda chaqiring
    user_id = event.from_user.id
    user_status = "admin" # DB dan olingan qiymat
    
    kb = admin_panel_kb(user_id=user_id, user_status=user_status)
    text = (
        f"🎛️ <b>ADMIN BOSHQARUV PANELI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Xush kelibsiz <b>{event.from_user.full_name}</b>\n"
        f"Kerakli bo'limni tanlang."
        
    )

    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    
    elif isinstance(event, types.CallbackQuery):
        # Callback bilan ishlaganda har doim 'answer' qiling
        await event.answer("Admin panel yuklandi")
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"❌ Admin panel xatosi: {e}")







@router.message(F.text == "👑 CREATOR PANEL")
@router.callback_query(F.data == "creator_panel")
async def creator_panel_handler(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id

    if user_id != config.CREATOR_ID:
        # Callback yoki Message ga qarab farqli javob
        if isinstance(event, types.CallbackQuery):
            await event.answer("🚫 Bu bo'lim faqat Creator uchun!", show_alert=True)
        else:
            await event.answer("🚫 Bu bo'lim faqat Creator uchun!")
        return

    kb = creator_panel_kb(creator_id=user_id)

    text = (
        f"👑 <b>CREATOR PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Salom Boss, <b>{event.from_user.full_name}</b>!\n"
        f"Bu yerda siz botning barcha boshqaruv imkoniyatlariga ega bo'lasiz. "
        f"Kerakli bo'limni tanlang."
    )

    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
        
    elif isinstance(event, types.CallbackQuery):
        await event.answer()  # Yuklanish animatsiyasini yopish
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise e