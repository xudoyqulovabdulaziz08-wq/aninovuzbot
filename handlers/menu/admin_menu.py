import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from keyboards.inline import admin_panel_kb
from    config import config

router = Router(name="admin_menu_router")
logger = logging.getLogger(__name__)


@router.message(F.text == "⚙️ SC ADMIN PANEL")
@router.callback_query(F.data == "admin_anime_panel")
async def admin_panel_handler(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    user_status = "admin" 
     # Bu yerda haqiqiy statusni tekshirish kerak

    kb = admin_panel_kb(user_id=user_id, user_status=user_status)

    text = (
        "🎛️ <b>ANIME BOSHQARUV PANELI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bu yerda siz anime ma'lumotlarini boshqarishingiz mumkin. "
        "Kerakli bo'limni tanlang."
    )

    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
        
    elif isinstance(event, types.CallbackQuery):
        await event.answer() # Tugmadagi yuklanish animatsiyasini yopish
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise e # Agar boshqa xatolik bo'lsa, uni ko'taramiz








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

    kb = admin_panel_kb(user_id=user_id, user_status="creator")

    text = (
        "👑 <b>CREATOR PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bu yerda siz botning barcha boshqaruv imkoniyatlariga ega bo'lasiz. "
        "Kerakli bo'limni tanlang."
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