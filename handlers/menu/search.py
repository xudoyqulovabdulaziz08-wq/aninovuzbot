import logging


from typing import Optional, Tuple
from urllib.parse import quote  

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from config import config


from keyboards.inline import search_inline_kb

router = Router(name="search_router")
logger = logging.getLogger(__name__)


@router.message(F.text == "🔍 Anime qidirish")
async def search_menu_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # 💡 Bu yerda bazadan yoki keshdan user VIPmi yo'qmi tekshirishingiz kerak
    # Hozircha oddiy tekshiruv:
    is_vip = False 
    
    # Creator va VIP lar uchun tugma
    is_privileged = is_vip or (user_id == config.CREATOR_ID)
    
    kb = search_inline_kb(is_privileged=is_privileged)

    text = (
        "🔍 <b>ANIME QIDIRISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Anime nomi, ID raqami yoki janr bo'yicha qidiruv imkoniyatlari mavjud. "
        "VIP foydalanuvchilar uchun tezkor qidiruv ham mavjud! "
        "Kerakli bo'limni tanlang va qidiruvni boshlang."
    )

    await message.answer(text, reply_markup=kb, parse_mode="HTML")