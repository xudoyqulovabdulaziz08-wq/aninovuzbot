import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import anime_menu_kb


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')

#==============================anime_menu================================#
#========================================================================#
@router.callback_query(F.data == "admin_anime_panel")
async def admin_anime_panel(callback: types.CallbackQuery, state: FSMContext): # event o'rniga callback
    await state.clear()

    text = (
        f"🎛️ <b>ANIME BOSHQARUV MENUSI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Xush kelibsiz, <b>{callback.from_user.full_name}</b>!\n\n"
        f"Boshqaruv paneli yuklandi.\n"
        f"Quyidagi bo'limlardan birini tanlang:\n"
    )
    
    kb = anime_menu_kb()

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Anime panel xatosi: {e}")
    finally:
        await callback.answer("🎛️ Anime boshqaruv menyusi")



@router.callback_query(F.data == "back_to_anime_panel")
async def back_to_anime_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await admin_anime_panel(callback, state)

