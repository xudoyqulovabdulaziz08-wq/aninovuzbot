import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Kesh va boshqa modullar (o'zingizniki)
from keyboards.inline import search_inline_kb 

class SearchState(StatesGroup):
    waiting_for_name = State()
    waiting_for_id = State()
    waiting_for_genre = State()

router = Router(name="search_router")
logger = logging.getLogger(__name__)



#==========================🔍 Anime qidirish=============================#
#========================================================================#
@router.message(F.text == "🔍 Anime qidirish")
async def search_menu_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    is_vip = False 
    is_privileged = is_vip or (user_id == config.CREATOR_ID)
    
    kb = search_inline_kb(is_privileged=is_privileged)

    text = (
        "🔍 <b>ANIME QIDIRISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Anime nomi, ID raqami yoki janr bo'yicha qidiruv imkoniyatlari mavjud. "
        "Kerakli bo'limni tanlang va qidiruvni boshlang."
    )

    await message.answer(text, reply_markup=kb, parse_mode="HTML")






#=========================back_to_search_menu============================#
#========================================================================#
# 🔥 TUZATISH: Dekorator qo'shildi va state.clear() await qilindi
@router.callback_query(F.data == "back_to_search_menu")
async def back_to_search_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear() 
    await callback_query.answer()
    
    # Menyu matnini qayta tiklash
    user_id = callback_query.from_user.id
    is_vip = False
    is_privileged = is_vip or (user_id == config.CREATOR_ID)
    kb = search_inline_kb(is_privileged=is_privileged)
    
    await callback_query.message.edit_text(
        "🔍 <b>ANIME QIDIRISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Anime nomi, ID raqami yoki janr bo'yicha qidiruv imkoniyatlari mavjud. "
        "Kerakli bo'limni tanlang va qidiruvni boshlang.",
        reply_markup=kb,
        parse_mode="HTML"
    )





#============================search_by_name==============================#
#========================================================================#
@router.callback_query(F.data == "search_by_name")
async def search_by_name(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer("Nomi bo'yicha qidiruv tanlandi.")
    await state.set_state(SearchState.waiting_for_name)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🔙 Orqaga", 
        callback_data="back_to_search_menu"
    ))
    
    try:
        await callback_query.message.edit_text(
            "📝 <b>Iltimos, qidirilayotgan anime nomini kiriting:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Xabarni o'zgartirish shart emas, barchasi joyida
            pass
        else:
            # Agar boshqa xatolik bo'lsa (masalan, xabar topilmadi), uni ko'taramiz
            raise e






#=============================search_by_id===============================#
#========================================================================#
@router.callback_query(F.data == "search_by_id")
async def search_by_id(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer("ID bo'yicha qidiruv tanlandi.")
    await state.set_state(SearchState.waiting_for_id)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🔙 Orqaga", 
        callback_data="back_to_search_menu"
    ))

    try:
        await callback_query.message.edit_text(
            "🆔 <b>Iltimos, qidirilayotgan anime ID raqamini kiriting:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Xabarni o'zgartirish shart emas, barchasi joyida
            pass
        else:
            # Agar boshqa xatolik bo'lsa (masalan, xabar topilmadi), uni ko'taramiz
            raise e




#===========================search_by_genre==============================#
#========================================================================#
@router.callback_query(F.data == "search_by_genre")
async def search_by_genre(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer("Genre bo'yicha qidiruv tanlandi.")
    await state.set_state(SearchState.waiting_for_genre)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🔙 Orqaga", 
        callback_data="back_to_search_menu"
    ))

    try:
        await callback_query.message.edit_text(
            "🎭 <b>Iltimos, qidirilayotgan anime janrini kiriting:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Xabarni o'zgartirish shart emas, barchasi joyida
            pass
        else:
            # Agar boshqa xatolik bo'lsa (masalan, xabar topilmadi), uni ko'taramiz
            raise e