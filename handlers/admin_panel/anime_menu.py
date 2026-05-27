import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from typing import Any, Optional
from aiogram.filters.callback_data import CallbackData


from sqlalchemy import select
from sqlalchemy.orm import selectinload


from database.repository import AnimeRepository
from database.connection import AsyncSession, async_sessionmaker

from config import config
from keyboards.inline import anime_menu_kb, add_anime_main_kb
from database.repository import AnimeRepository
from database.connection import AsyncSession
from database.models import Anime, Genre


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


class AnimeMenuState(StatesGroup):
    adding_anime_name = State() # 1 yangi anime qo'shish uchun nomini kiritish
    adding_anime_photo = State() # 2 yangi anime qo'shish uchun rasmni kiritish
    adding_genres = State() # 3 yangi anime qo'shish uchun janrlarni kiritish
    adding_year = State() # 5 yangi anime qo'shish uchun chiqarilgan yilni kiritish
    adding_description = State() # 6 yangi anime qo'shish uchun tavsifni kiritish
    adding_laguages = State() # 7 yangi anime qo'shish uchun tillarni kiritish
    adding_episode_video = State()
    deleting_anime = State()
    updating_anime = State()

class AnimeMenuCallbacks:
    ADD_ANIME = "add_anime"
    ADD_GENRES = "add_genres"
    ADD_YEAR = "add_year"
    ADD_DESCRIPTION = "add_description"
    ADD_EPISODE = "add_episode"
    ADD_PHOTO = "add_photo"
    ADD_LANGUAGES = "add_languages"
    DELETE_ANIME = "delete_anime"
    UPDATE_ANIME = "update_anime"

    
class AnimePageCallback(CallbackData, prefix="anime_page"):
    page: int

class AnimeDetailCallback(CallbackData, prefix="anime_detail"):
    anime_id: int
    page: int

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






#============================add_anime_main==============================#
#========================================================================#
@router.callback_query(F.data == "add_anime")
async def add_anime_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    text = (
        f"<b>ANIME QO'SHISH BO'LIMI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Quyidagi bo'limlardan birini tanlang:\n"
    )


    kb = add_anime_main_kb()

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Anime panel xatosi: {e}")
    finally:
        await callback.answer("💫 ANIME QO'SHISH MENUSI")

















