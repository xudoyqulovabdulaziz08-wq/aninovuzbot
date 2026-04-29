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





@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu") # 👈 Orqaga tugmasi uchun callback
async def buy_vip(event: Union[types.Message, types.CallbackQuery], user: DBUser, session: AsyncSession = None):
    # Agar tugma bosilgan bo'lsa, 'message' obyektini ichidan olamiz
    message = event.message if isinstance(event, types.CallbackQuery) else event

    if session is None or user is None:
        return await message.answer("⚠️ Tizimda vaqtincha uzilish bor.")

    uzb_tz = pytz.timezone('Asia/Tashkent')
    
    if user.is_vip and user.vip_expire_date:
        ve_aware = user.vip_expire_date.replace(tzinfo=pytz.UTC).astimezone(uzb_tz)
        status_info = f"🌟 <b>Siz hozirda VIP foydalanuvchisiz!</b>\n⏳ Muddat: <b>{ve_aware.strftime('%d.%m.%Y | %H:%M')}</b> gacha."
        btn_text = "🔄 VIP muddatini uzaytirish"
    else:
        status_info = "🌑 Siz hozirda <b>Oddiy</b> rejimdasiz."
        btn_text = "💳 VIP sotib olish"

    text = (
        f"💎 <b>VIP PREMIYUM TIZIMI</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{status_info}\n\n"
        f"<b>✨ VIP imkoniyatlari:</b>\n"
        f"🚀 <b>Yuqori tezlik:</b> Videolarni maksimal tezlikda ko'rish\n"
        f"🚫 <b>Reklamasiz:</b> Botdan hech qanday reklamalarsiz foydalanish\n"
        f"📂 <b>Eksklyuziv:</b> Faqat VIP uchun ochiq pre-relizlar\n"
        f"👑 <b>Maxsus status:</b> Ismingiz yonida oltin belgi\n\n"
        f"💰 <b>Bonus vip:</b> 100 ball = 30 kunlik VIP\n"
        f"━━━━━━━━━━━━━━\n"
        f"👇 <i>Pastdagi tugma orqali VIP sotib olishingiz mumkin:</i>"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_text, callback_data="buy_vip_start")],
        [types.InlineKeyboardButton(text="🎁 Do'stlarni taklif qilib ball yig'ish", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="👤 <b>SHAXSIY KABINET", callback_data="personal_cabinet")]
        
    ])

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await event.answer()
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "buy_vip_start")
async def buy_vip_start_handler(callback: types.CallbackQuery, user: DBUser):
    # Narxlar jadvali chiroyliroq ko'rinishda
    text = (
        f"💳 <b>VIP SOTIB OLISH (TARIFLAR)</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🤖 <b>To'lov usullari:</b>\n"
        f"Hozirda avtomatik to'lov (Click/Payme) ulanmoqda. \n"
        f"Hozircha xaridlar <b>Admin</b> orqali amalga oshiriladi.\n\n"
        f"💎 <b>TARIFLAR:</b>\n"
        f"▫️ 1 oy — <b>23,000 so'm</b>\n"
        f"▫️ 3 oy — <b>55,000 so'm</b> (14% chegirma)\n"
        f"▫️ 6 oy — <b>90,000 so'm</b> (35% chegirma)\n"
        f"▫️ 12 oy — <b>170,000 so'm</b> 🔥 (Eng arzon!)\n"
        f"━━━━━━━━━━━━━━\n"
        f"📩 <i>Sotib olish uchun quyidagi tugmani bosing:</i>"
    )
    
    # Adminga tayyor matn bilan yuborish
    admin_username = "Khudoyqulov_pg"
    admin_url = f"https://t.me/{admin_username}?text=Assalomu+alaykum+VIP+sotib+olmoqchiman.+ID:{user.user_id}"
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💬 Adminga yozish", url=admin_url)],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="buy_vip_menu")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()