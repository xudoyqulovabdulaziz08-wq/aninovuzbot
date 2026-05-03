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
from aiogram.fsm.context import FSMContext

router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)








import pytz
from datetime import datetime, timezone
from typing import Union
from aiogram import types, F
from aiogram.exceptions import TelegramBadRequest

@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu")
async def buy_vip(event: Union[types.Message, types.CallbackQuery], user: dict, state: FSMContext, session: AsyncSession):
    """
    VIP menyusi: L1/L2 keshdan olingan ma'lumotlar bilan tezkor ishlash.
    """
    await state.clear()
    is_cb = isinstance(event, types.CallbackQuery)
    message = event.message if is_cb else event

    # 1. CIRCUIT BREAKER & USER CHECK
    # Middleware 'user' dict qaytaradi, session esa SafeSession obyekti.[cite: 1]
    if not user:
        msg = "⚠️ Ma'lumotlarni yuklashda xatolik. Keyinroq urinib ko'ring."
        return await event.answer(msg, show_alert=True) if is_cb else await message.answer(msg)

    # 2. VIP STATUS LOGIC (Dict formatiga moslangan)
    uzb_tz = pytz.timezone('Asia/Tashkent')
    is_vip = False
    v_expire = user.get("vip_expire_date") # Timestamp formatida keladi[cite: 1]

    if v_expire:
        # Timestampni datetime obyektiga o'tkazish
        ve_dt = datetime.fromtimestamp(v_expire, tz=timezone.utc)
        if ve_dt > datetime.now(timezone.utc):
            is_vip = True
            ve_local = ve_dt.astimezone(uzb_tz)
            status_info = (
                f"🌟 <b>Sizning holatingiz:</b> <pre>VIP PREMIUM</pre>\n"
                f"⏳ Muddat: <b>{ve_local.strftime('%d.%m.%Y | %H:%M')}</b>"
            )
            btn_text = "🔄 Muddatni uzaytirish"
        else:
            status_info = "🌑 <b>Sizning holatingiz:</b> <pre>ODDIY FOYDALANUVCHI</pre>"
            btn_text = "💳 VIP sotib olish"
    else:
        status_info = "🌑 <b>Sizning holatingiz:</b> <pre>ODDIY FOYDALANUVCHI</pre>"
        btn_text = "💳 VIP sotib olish"

    # 3. TEXT & UI (Premium Design)
    points = user.get("points", 0)
    
    text = (
        "💎 <b>VIP PREMIYUM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_info}\n"
        f"💰 Balans: <b>{points} ball</b>\n\n"
        "✨ <b>VIP imkoniyatlari:</b>\n"
        "🚀 <b>Yuqori tezlik:</b> Kontentga cheksiz kirish\n"
        "🚫 <b>Reklamasiz:</b> Hech qanday ortiqcha xabarlarsiz\n"
        "📂 <b>Eksklyuziv:</b> Faqat VIP uchun maxsus kanallar\n"
        "👑 <b>Status:</b> Ismingiz yonida maxsus belgi\n\n"
        "🏷 <b>Tarif:</b> <code>100 ball = 30 kun</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 VIP faollashtirish uchun tugmani bosing:"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=btn_text, callback_data="buy_vip_start")],
        [
            types.InlineKeyboardButton(text="🎁 Ball yig'ish", callback_data="get_ref_link"),
            types.InlineKeyboardButton(text="👤 Kabinet", callback_data="back_to_cabinet"),
        ]
    ])

    # 4. SEND/EDIT LOGIC
    try:
        if is_cb:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await event.answer()
        else:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            # Agar edit qilishda muammo bo'lsa (masalan rasm ustidagi tugma), yangi xabar yuboradi
            await message.answer(text, reply_markup=kb, parse_mode="HTML")









@router.callback_query(F.data == "buy_vip_start")
async def buy_vip_start_handler(callback: types.CallbackQuery, user: dict):
    """
    VIP tariflar menyusi: Xavfsiz URL va kesh mantiqi bilan integratsiya qilingan.
    """
    # 1. USER VALIDATION (L1/L2 keshdan kelgan dict)[cite: 1]
    if not user:
        return await callback.answer(
            "⚠️ Ma'lumot topilmadi. Qayta /start bosing.", 
            show_alert=True
        )

    user_id = user.get("user_id") # Middleware orqali kelgan ID[cite: 1]
    
    # 2. CONTENT BUILDER (Premium UX)
    text = (
        "💳 <b>VIP PREMIUM TARIFLAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>To‘lov usuli:</b>\n"
        "Hozirda to'lovlar avtomatlashtirilmoqda.\n"
        "Sotib olish uchun admin bilan bog'laning.\n\n"
        "💎 <b>Paketlar (So'mda):</b>\n"
        "▫️ 1 oy — <b>23 000 so‘m</b>\n"
        "▫️ 3 oy — <b>55 000 so‘m</b>\n"
        "▫️ 6 oy — <b>90 000 so‘m</b>\n"
        "▫️ 12 oy — <b>170 000 so‘m</b> 🔥\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <i>Eslatma: 100 ball to'plab 1 oylik VIP olishingiz ham mumkin!</i>\n\n"
        "👇 Paketni tanlang yoki adminga murojaat qiling:"
    )

    # 3. SECURE ADMIN LINK
    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, VIP sotib olmoqchiman. ID: {user_id}"
    # Xavfsizlik uchun URL encode qilish shart
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    # 4. KEYBOARD DESIGN
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="💎 1 oy", callback_data="vip_1"),
            types.InlineKeyboardButton(text="💎 3 oy", callback_data="vip_3"),
        ],
        [
            types.InlineKeyboardButton(text="💎 6 oy", callback_data="vip_6"),
            types.InlineKeyboardButton(text="🔥 12 oy", callback_data="vip_12"),
        ],
        [
            types.InlineKeyboardButton(
                text="🎁 Ball orqali olish (100 ball)", 
                callback_data="exchange_points"
            )
        ],
        [
            types.InlineKeyboardButton(text="💬 Admin bilan bog'lanish", url=admin_url)
        ],
        [
            types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="buy_vip_menu")
        ]
    ])

    # 5. SAFE MESSAGE EDITING
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            await callback.answer() # Hech narsa o'zgarmasa shunchaki javob qaytarish
        elif "message can't be edited" in err_msg:
            # Agar eski xabar bo'lsa, yangisini yuborish
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            await callback.message.delete()
        else:
            # Boshqa kutilmagan xatolar uchun
            raise e

    await callback.answer()



from urllib.parse import quote
from aiogram import types, F
from aiogram.exceptions import TelegramBadRequest

@router.callback_query(F.data.startswith("vip_"))
async def vip_choice_handler(callback: types.CallbackQuery, user: dict):
    """
    VIP tarif tanlash: Keshdan foydalanuvchi ma'lumotlarini olish va 
    xavfsiz URL yaratish orqali tezkor ishlashni ta'minlaydi.[cite: 1, 6]
    """
    # 1. USER VALIDATION (Middleware keshidan kelgan dict)
    if not user:
        return await callback.answer(
            "⚠️ Ma'lumot topilmadi. Qayta urinib ko'ring.", 
            show_alert=True
        )

    user_id = user.get("user_id") # Middleware formatiga mos

    # 2. DATA PARSING
    try:
        months = callback.data.split("_", 1)[1]
    except (IndexError, AttributeError):
        return await callback.answer("❌ Ma'lumotda xatolik.", show_alert=True)

    prices = {
        "1": "23 000",
        "3": "55 000",
        "6": "90 000",
        "12": "170 000"
    }

    if months not in prices:
        return await callback.answer("🚫 Bunday tarif mavjud emas.", show_alert=True)

    price = prices[months]

    # 3. PREMIUM UI DESIGN
    text = (
        f"💎 <b>{months} OYLIK VIP PREMIUM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Tarif narxi: <b>{price} so‘m</b>\n"
        f"👤 Foydalanuvchi ID: <code>{user_id}</code>\n\n"
        "📝 <b>Yo'riqnoma:</b>\n"
        "1. Adminga o'ting va to'lov rekvizitlarini oling.\n"
        "2. To'lovdan so'ng chekni (skrinshot) yuboring.\n"
        "3. Admin 5-15 daqiqa ichida VIPni faollashtiradi.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Pastdagi tugma orqali murojaat qiling:"
    )

    # 4. SECURE MESSAGE BUILDER
    msg = (
        f"Assalomu alaykum admin, VIP paket tanladim.\n"
        f"📅 Muddat: {months} oy\n"
        f"💸 Narxi: {price} so‘m\n"
        f"🆔 User ID: {user_id}"
    )
    # URL xavfsizligi (Pro daraja)[cite: 1]
    admin_url = f"https://t.me/Khudoyqulov_pg?text={quote(msg)}"

    # 5. KEYBOARD DESIGN
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💬 Adminga murojaat qilish", url=admin_url)],
        [types.InlineKeyboardButton(text="🔙 Tariflarga qaytish", callback_data="buy_vip_start")]
    ])

    # 6. HIGH-PERFORMANCE RESPONSE (Safe Edit)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            await callback.answer()
        elif "message can't be edited" in err_msg:
            # Agar xabarni tahrirlab bo'lmasa, yangisini yuborib eskisini o'chirish
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            await callback.message.delete()
        else:
            raise e

    await callback.answer()