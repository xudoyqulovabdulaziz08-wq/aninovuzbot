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
from aiogram.exceptions import TelegramBadRequest
from urllib.parse import quote


router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)








@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu")
async def buy_vip(event: Union[types.Message, types.CallbackQuery], user: DBUser, session: AsyncSession = None):
    is_callback = isinstance(event, types.CallbackQuery)
    message = event.message if is_callback else event

    if not message:
        return

    # Avvalgi darslardan olingan "Circuit Breaker" himoyasi
    if session is None or user is None:
        msg = "⚠️ Xizmat vaqtincha ishlamayapti. Keyinroq urinib ko‘ring."
        if is_callback:
            return await event.answer(msg, show_alert=True)
        return await message.answer(msg)

    uzb_tz = pytz.timezone('Asia/Tashkent')

    if user.is_vip and user.vip_expire_date:
        ve = user.vip_expire_date
        if ve.tzinfo is None:
            ve = ve.replace(tzinfo=datetime.timezone.utc) # datetime importiga e'tibor bering
        ve = ve.astimezone(uzb_tz)

        status_info = f"🌟 <b>Siz VIP foydalanuvchisiz!</b>\n⏳ Muddat: <b>{ve.strftime('%d.%m.%Y | %H:%M')}</b>"
        btn_text = "🔄 VIP muddatini uzaytirish"
    else:
        status_info = "🌑 Siz oddiy foydalanuvchisiz."
        btn_text = "💳 VIP sotib olish"

    # Ballarni ko'rsatish (User tajribasi uchun qulay)
    user_points = getattr(user, 'points', 0)

    text = (
        "💎 <b>VIP PREMIYUM</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"{status_info}\n"
        f"💰 Sizning ballaringiz: <b>{user_points} ball</b>\n\n"
        "✨ <b>VIP imkoniyatlari:</b>\n"
        "🚀 Yuqori tezlik\n"
        "🚫 Reklamasiz foydalanish\n"
        "📂 Eksklyuziv kontent\n"
        "👑 Maxsus status\n\n"
        "🏷 <b>Narxi:</b> 100 ball = 30 kun VIP\n"
        "━━━━━━━━━━━━━━\n"
        "👇 Quyidagi tugma orqali faollashtiring:"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_text, callback_data="buy_vip_start")],
        [
            types.InlineKeyboardButton(text="🎁 Ball yig'ish", callback_data="get_ref_link"),
            types.InlineKeyboardButton(text="👤 Kabinet", callback_data="back_to_cabinet"),
        ]
    ])

    try:
        if is_callback:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await event.answer()
        else:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if "message is not modified" in error_text:
            await event.answer()
        elif "message can't be edited" in error_text:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            raise e







@router.callback_query(F.data == "buy_vip_start")
async def buy_vip_start_handler(callback: types.CallbackQuery, user: DBUser):
    # User obyektini tekshirish
    if user is None:
        return await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)

    text = (
        "💳 <b>VIP TARIFLAR</b>\n"
        "━━━━━━━━━━━━━━\n"
        "🤖 <b>To‘lov usuli:</b>\n"
        "Hozircha admin orqali amalga oshiriladi.\n\n"
        "💎 <b>Narxlar (So'mda):</b>\n"
        "▫️ 1 oy — <b>23 000 so‘m</b>\n"
        "▫️ 3 oy — <b>55 000 so‘m</b>\n"
        "▫️ 6 oy — <b>90 000 so‘m</b>\n"
        "▫️ 12 oy — <b>170 000 so‘m</b> 🔥\n"
        "━━━━━━━━━━━━━━\n"
        "✨ <i>Eslatma: 100 ball to'plab 1 oylik VIP olishingiz ham mumkin!</i>\n\n"
        "👇 Paketni tanlang yoki adminga yozing:"
    )

    admin_username = "Khudoyqulov_pg"
    # Adminga boradigan tayyor shablon xabar
    msg = f"Assalomu alaykum, VIP sotib olmoqchiman. ID:{user.user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(msg)}"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="1 oy", callback_data="vip_1"),
            types.InlineKeyboardButton(text="3 oy", callback_data="vip_3"),
        ],
        [
            types.InlineKeyboardButton(text="6 oy", callback_data="vip_6"),
            types.InlineKeyboardButton(text="12 oy", callback_data="vip_12"),
        ],
        [
            # Agar ball orqali olish funksiyasi bo'lsa:
            types.InlineKeyboardButton(text="🎁 Ball orqali olish (100 ball)", callback_data="buy_vip_points")
        ],
        [
            types.InlineKeyboardButton(text="💬 Adminga yozish", url=admin_url)
        ],
        [
            types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="buy_vip_menu")
        ]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message can't be edited" in err:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        elif "message is not modified" not in err:
            raise

    await callback.answer()




@router.callback_query(F.data.startswith("vip_"))
async def vip_choice_handler(callback: types.CallbackQuery, user: DBUser):
    if user is None:
        return await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)

    try:
        months = callback.data.split("_", 1)[1]
    except (IndexError, AttributeError):
        return await callback.answer("Xatolik yuz berdi.", show_alert=True)

    prices = {
        "1": "23 000",
        "3": "55 000",
        "6": "90 000",
        "12": "170 000"
    }

    if months not in prices:
        return await callback.answer("Noto‘g‘ri tarif.", show_alert=True)

    price = prices[months]

    text = (
        f"💎 <b>{months} OYLIK VIP</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💰 Narxi: <b>{price} so‘m</b>\n\n"
        "📸 To‘lovdan so‘ng skrinshot yuboring\n"
        "yoki quyidagi tugma orqali admin bilan bog‘laning."
    )

    msg = (
        f"Assalomu alaykum, men {months} oylik VIP paketni tanladim.\n"
        f"Narxi: {price} so‘m\n"
        f"User ID: {user.user_id}"
    )

    admin_url = f"https://t.me/Khudoyqulov_pg?text={quote(msg)}"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💬 Adminga yozish", url=admin_url)],
        [types.InlineKeyboardButton(text="🔙 Tariflarga qaytish", callback_data="buy_vip_start")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if "message can't be edited" in error_text:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        elif "message is not modified" not in error_text:
            raise

    await callback.answer()