# handlers/search.py

# DIQQAT: select ni sqlalchemy dan olish shart!
from sqlalchemy import select 
from aiogram import types, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy.ext.asyncio import AsyncSession # To'g'ri tip

from keyboards.inline import search_inline_kb
from database.models import DBUser

router = Router()

# Qidiruv holatlarini belgilaymiz
class SearchStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_id = State()
    waiting_for_genre = State()

@router.message(F.text == "🔍 Anime qidirish")
async def anime_search(message: types.Message, session: AsyncSession):
    """Asosiy qidiruv menyusini chiqarish."""
    
    # 1. Foydalanuvchini bazadan qidiramiz
    stmt = select(DBUser).where(DBUser.user_id == message.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    # VIP statusni aniqlaymiz
    is_vip = user.is_vip if user else False

    await message.answer(
        "🔍 <b>Anime qidiruv bo'limiga xush kelibsiz!</b>\n\n"
        "Quyidagi tugmalardan birini tanlab, qidiruvni boshlang:",
        reply_markup=search_inline_kb(is_vip=is_vip),
        parse_mode="HTML"
    )

# --- CALLBACK HANDLERLAR ---

@router.callback_query(F.data == "search_by_name")
async def start_name_search(callback: types.CallbackQuery, state: FSMContext):
    # Bekor qilish tugmasini qo'shsak yaxshi bo'ladi
    cancel_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_search")]
    ])
    
    await callback.message.edit_text(
        "📝 Anime <b>nomini</b> kiriting:",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(SearchStates.waiting_for_name)
    await callback.answer()

@router.callback_query(F.data == "search_by_id")
async def start_id_search(callback: types.CallbackQuery, state: FSMContext):
    cancel_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_search")]
    ])
    
    await callback.message.edit_text(
        "🔢 Anime <b>ID raqamini</b> kiriting:",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(SearchStates.waiting_for_id)
    await callback.answer()

# Bekor qilish handlerini optimallashtiramiz
@router.callback_query(F.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    # 1. Holatni tozalaymiz
    await state.clear()
    
    # 2. Foydalanuvchining VIP statusini qayta tekshiramiz 
    # (Chunki menyuni qayta chiqarish uchun bu kerak)
    stmt = select(DBUser).where(DBUser.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    is_vip = user.is_vip if user else False

    # 3. Xabarni o'chirib yangi xabar yubormaymiz, balki o'zini tahrirlaymiz
    await callback.message.edit_text(
        "🔍 <b>Anime qidiruv bo'limiga qaytdingiz.</b>\n\n"
        "Quyidagi qidiruv usullaridan birini tanlang:",
        reply_markup=search_inline_kb(is_vip=is_vip),
        parse_mode="HTML"
    )
    
    # 4. Bildirishnoma (Toast) yuboramiz
    await callback.answer("Qidiruv bekor qilindi")