import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from config import config

from keyboards.inline import get_ranked_kb


router = Router(name="reyting_router")
logger = logging.getLogger(__name__)


#==============================🌟 Reyting================================#
#========================================================================#
@router.message(F.text == "🌟 Reyting")
@router.callback_query(F.data == "reyting_menu")
async def ranked_menu(event: types.Message | types.CallbackQuery, state: FSMContext):
    await state.clear()

    kb = get_ranked_kb()
    
    text = (
        "🌟 <b>REYTING BO'LIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang va eng yaxshilarni kashf eting: 🔍\n\n"
        "🎬 <b>Anime Reyting</b>\n"
        "└ <i>Eng ko'p ko'rilgan va ommabop animelar</i>\n\n"
        "🏆 <b>Top Foydalanuvchilar</b>\n"
        "└ <i>Eng faol va yuqori ballga ega userlar</i>\n\n"
        "🚀 <i>Yangi tizimlar ustida ish olib bormoqdamiz...</i>"
    )
    try:
        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        elif isinstance(event, types.CallbackQuery):
            await event.answer() # Tugmadagi yuklanish animatsiyasini yopish
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise e # Agar boshqa xatolik bo'lsa, uni ko'taramiz
    

    
    