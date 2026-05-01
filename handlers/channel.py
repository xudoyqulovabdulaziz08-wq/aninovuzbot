import datetime
import logging
from aiogram import Router, types, F
import pytz
from database.models import DBUser, Channel
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from keyboards.inline import admin_panel_kb, creator_panel_kb
from datetime import datetime

router = Router()

@router.callback_query(F.data == "admin_channels")
async def admin_channels_l(callback: types.CallbackQuery, session: AsyncSession):

    channels = await session.execute(
        select(Channel).where(Channel.is_active == True)
    )
    channels = channels.scalars().all()

    text = (
        "<b>📢 KANALLAR BO'LIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📌 Bu bo‘lim orqali siz:\n"
        "➕ Kanal qo‘shish\n"
        "📢 Kanallar ro‘yxatini ko‘rish\n"
        "➖ Kanal o‘chirish\n"
    )

    if channels:
        text += "\n📋 <b>Faol kanallar:</b>\n"
        for ch in channels:
            text += f"• {ch.title}\n"
    else:
        text += "\n⚠️ Hozircha kanal yo‘q"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Kanal qo‘shish", callback_data="add_channel_start")],
        [types.InlineKeyboardButton(text="📢 Kanallar ro‘yxati", callback_data="full_channel")],
        [types.InlineKeyboardButton(text="➖ Kanal o‘chirish", callback_data="del_channel_start")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel_back")]
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()