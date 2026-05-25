import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import creator_panel_kb, creator_db_panel_kb
router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


#========================creator_manage_admins===========================#
#========================================================================#
@router.callback_query(F.data == "creator_panel")
async def creator_panel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    # 1. Xavfsizlik tekshiruvi
    if callback.from_user.id != int(CREATOR_ID): # ID ni int ga o'girib solishtiring
        await callback.answer("❌ Siz Creator emassiz!", show_alert=True)
        return

    # 2. Klaviatura va Matn
    kb = creator_panel_kb()
    text = (
        f"👑 <b>CREATOR PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Xush kelibsiz, <b>{callback.from_user.full_name}</b>!\n"
        f"Tizim to'liq nazorat ostida."
    )

    # 3. Faqat CallbackQuery uchun handler (Router dekoratorida callback deb belgilaganingiz uchun)
    await callback.answer("Creator panel yuklandi")
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Creator panel xatosi: {e}")






@router.callback_query(F.data == "creator_db_panel")
async def creator_db_panel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    # 1. Xavfsizlik tekshiruvi
    if callback.from_user.id != int(CREATOR_ID): # ID ni int ga o'girib solishtiring
        await callback.answer("❌ Siz Creator emassiz!", show_alert=True)
        return

    # 2. Klaviatura va Matn
    kb = creator_db_panel_kb() # Albatta, creator_db_panel_kb() ni yaratishingiz kerak
    text = (
        f"👑 <b>CREATOR DB PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Bu yerda ma'lumotlar bazasini boshqarish imkoniyatlari mavjud.\n"
        f"Ehtiyotkorlik bilan foydalaning!"
    )


    # 3. Faqat CallbackQuery uchun handler (Router dekoratorida callback deb belgilaganingiz uchun)
    await callback.answer("Creator DB panel yuklandi")
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Creator DB panel xatosi: {e}")