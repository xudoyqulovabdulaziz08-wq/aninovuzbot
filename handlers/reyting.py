import pytz
import logging
from datetime import datetime, timezone
from aiogram import types, F, Router
from typing import Any, Union  # ✅ To'g'risi shu
from sqlalchemy import select, desc
from database.models import DBUser
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
from database.cache import valkey
router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)



from typing import Union

@router.message(F.text == "🌟 Reyting")
@router.callback_query(F.data == "reyting_menu")
async def ranked_full(event: Union[types.Message, types.CallbackQuery], user: DBUser, session: AsyncSession = None):
    # Event turini aniqlaymiz
    is_callback = isinstance(event, types.CallbackQuery)
    message = event.message if is_callback else event

    text = (
        f"🌟 <b>REYTING BO'LIMI</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"Kerakli bo'limni tanlang:\n"
        f"▫️ <b>Anime reyting</b> — Eng ko'p ko'rilgan animelar\n"
        f"▫️ <b>User reyting</b> — Eng ko'p do'stini taklif qilganlar"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎬 Anime reyting", callback_data="Anime_ranked")],
        [types.InlineKeyboardButton(text="🏆 Top foydalanuvchilar", callback_data="User_ranked")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_cabinet")]
    ])

    if is_callback:
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
        await event.answer()
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

