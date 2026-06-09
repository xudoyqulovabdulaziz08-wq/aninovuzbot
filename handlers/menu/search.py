import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from config import config
# Kesh va boshqa modullar (o'zingizniki)
from keyboards.inline import search_inline_kb 

class SearchState(StatesGroup):
    waiting_for_name = State()
    waiting_for_id = State()
    waiting_for_genre = State()

router = Router()
logger = logging.getLogger(__name__)


# ========================================================================
# 🧩 QIDIRUV MENYUSI TARKIBINI SHAKLLANTIRUVCHI FUNKSIYA (DRY Prinsipi)
# ========================================================================
def get_search_menu_content(user_id: int) -> tuple[str, types.InlineKeyboardMarkup]:
    """ 
    Asosiy qidiruv menyusi matni va klaviaturasini qaytaruvchi yordamchi funksiya. 
    Bu funksiya kodni takrorlanishdan asraydi (Message va Callback uchun umumiy).
    """
    is_vip = False 
    is_privileged = is_vip or (user_id == config.CREATOR_ID)
    
    kb = search_inline_kb(is_privileged=is_privileged)

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🔍 <b>QIDIRUV BO'LIMI</b> 🔍\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Qidiruv turini tanlang, o'z hududingizni kengaytiring! 🌌\n\n"
        "📝 <b>Nomi bo'yicha:</b> <i>Anime yoki qahramon ismini yozing</i>\n"
        "🆔 <b>Maxfiy kod (ID):</b> <i>Aniqlik bilan topish uchun</i>\n"
        "🎭 <b>Janr bo'yicha:</b> <i>O'zingizga yoqqan yo'nalishni tanlang</i>"
    )
    return text, kb


# ========================================================================
# 🔍 ANIME QIDIRISH ASOSIY MENYUSI (MESSAGE)
# ========================================================================
@router.message(F.text == "🔍 Anime qidirish")
async def search_menu_handler(message: types.Message, state: FSMContext):
    if state:
        await state.clear()
        
    text, kb = get_search_menu_content(message.from_user.id)

    try:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Qidiruv menyusini yuborishda xatolik: {e}")


# ========================================================================
# 🔄 ASOSIY MENYUGA QAYTISH (CALLBACK)
# ========================================================================
@router.callback_query(F.data == "back_to_search_menu")
async def back_to_search_menu(callback: types.CallbackQuery, state: FSMContext):
    if state:
        await state.clear() 
    
    text, kb = get_search_menu_content(callback.from_user.id)
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Qidiruv menyusiga qaytishda xatolik: {e}")
    finally:
        await callback.answer()


# ========================================================================
# 📝 1. NOMI BO'YICHA QIDIRISH
# ========================================================================
@router.callback_query(F.data == "search_by_name")
async def search_by_name(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.waiting_for_name)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⛩ Ortga qaytish", callback_data="back_to_search_menu"))
    
    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   📝 <b>NOMI BO'YICHA QIDIRUV</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Siz qidirayotgan animening to'liq yoki qisqacha nomini kiriting. "
        "<i>Masalan: Jujutsu Kaisen, Naruto</i> ✍️"
    )

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Nomi bo'yicha qidiruv xatoligi: {e}")
    finally:
        await callback.answer("Nomi bo'yicha qidiruv  faollashdi ⚡️")


# ========================================================================
# 🆔 2. ID BO'YICHA QIDIRISH
# ========================================================================
@router.callback_query(F.data == "search_by_id")
async def search_by_id(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.waiting_for_id)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⛩ Ortga qaytish", callback_data="back_to_search_menu"))

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🆔 <b> KOD (ID)</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Aniqlik - eng yaxshi qurol! 🎯\n"
        "Iltimos, qidirilayotgan anime yoki seriyaning maxsus ID raqamini kiriting:"
    )

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ ID bo'yicha qidiruv xatoligi: {e}")
    finally:
        await callback.answer("Maxfiy kod tizimi faollashdi 🔐")


# ========================================================================
# 🎭 3. JANR BO'YICHA QIDIRISH
# ========================================================================
@router.callback_query(F.data == "search_by_genre")
async def search_by_genre(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.waiting_for_genre)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⛩ Ortga qaytish", callback_data="back_to_search_menu"))

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🎭 <b>JANRLAR OLAMI</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Sizning didingizga nima mos keladi? 🔮\n"
        "Iltimos, izlayotgan janringizni kiriting <i>(Masalan: Shounen, Isekai, Romantika)</i>:"
    )

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Janr bo'yicha qidiruv xatoligi: {e}")
    finally:
        await callback.answer("Janr qidirish bo'limi ochildi 🎭")