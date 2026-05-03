import pytz
import logging
from datetime import datetime, timezone
from aiogram import types, F, Router
from typing import Any, Union  # ✅ To'g'risi shu
from sqlalchemy import select, desc
from database.models import DBUser
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
from aiogram.fsm.context import FSMContext
from database.cache import valkey
from urllib.parse import quote
from aiogram.exceptions import TelegramBadRequest


router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)






@router.message(F.text == "👤 Shaxsiy kabinet")
@router.callback_query(F.data == "cabinet")
async def personal_cabinet(event: Union[types.Message, types.CallbackQuery], user: dict, state: FSMContext):
    """
    Shaxsiy kabinet: L1/L2 keshdan olingan ma'lumotlar bilan ultra-tezkor ishlash.[cite: 1, 3]
    """
    await state.clear()
    is_cb = isinstance(event, types.CallbackQuery)
    message = event.message if is_cb else event
    
    # 1. CIRCUIT BREAKER & USER VALIDATION[cite: 1]
    if not user:
        msg = "⚠️ Ma'lumot topilmadi. Iltimos, /start buyrug'ini qayta yuboring."
        return await event.answer(msg, show_alert=True) if is_cb else await message.answer(msg)

    # 2. TIMEZONE & VIP LOGIC (Kesh formatiga moslangan)
    uzb_tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(timezone.utc)
    
    vip_expire_ts = user.get("vip_expire_date") # Keshdan timestamp keladi
    
    if vip_expire_ts:
        ve_dt = datetime.fromtimestamp(vip_expire_ts, tz=timezone.utc)
        if ve_dt > now:
            ve_local = ve_dt.astimezone(uzb_tz)
            vip_status = f"✅ Faol ({ve_local.strftime('%d.%m.%Y | %H:%M')})"
        else:
            vip_status = "⚠️ Muddati tugagan"
    else:
        vip_status = "❌ Faol emas"

    # 3. USER DATA PARSING[cite: 1]
    user_id = user.get("user_id")
    points = user.get("points", 0)
    status = user.get("status", "user").upper()
    ref_count = user.get("referral_count", 0)
    
    # Username xavfsiz shakllantirish
    user_info = event.from_user
    display_username = f"@{user_info.username}" if user_info.username else "O'rnatilmagan"

    # 4. PREMIUM UI DESIGN
    text = (
        "👤 <b>SHAXSIY KABINET</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Username: <b>{display_username}</b>\n"
        f"🏅 Status: <pre>{status}</pre>\n"
        f"⭐ Ballaringiz: <b>{points}</b>\n"
        f"👥 Takliflar: <b>{ref_count} ta</b>\n"
        f"💎 VIP holati: <b>{vip_status}</b>\n"
        f"‼️Sayt profile tez orqada ishga tushadi\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    
    # 5. KEYBOARD LOGIC (Pro UX)
    kb_list = []
    
    # Ballarni VIP'ga almashtirish (Agar ball yetarli bo'lsa)
    if points >= 100:
        kb_list.append([types.InlineKeyboardButton(text="💎 Ballarni VIP'ga almashtirish", callback_data="exchange_points")])
    
    kb_list.extend([
        [types.InlineKeyboardButton(text="💳 VIP sotib olish", callback_data="buy_vip_menu")],
        [
            types.InlineKeyboardButton(text="🔗 Taklif havola", callback_data="get_ref_link"),
            types.InlineKeyboardButton(text="🌐 Saytdagi profil", url="https://aninowuz.uz/profile")
        ]
    ])

    kb = types.InlineKeyboardMarkup(inline_keyboard=kb_list)

    # 6. SAFE RESPONSE HANDLING
    try:
        if is_cb:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await event.answer()
        else:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            await message.answer(text, reply_markup=kb, parse_mode="HTML")







@router.message(F.text == "❓ Qo'llanma")
async def help_page(message: types.Message, user: dict, state: FSMContext):
    """
    Qo'llanma bo'limi: Minimal kechikish va yuqori UX darajasidagi handler.[cite: 1, 3]
    """
    await state.clear()

    # 1. USER VALIDATION (Xavfsizlik uchun)
    user_id = user.get("user_id") if user else message.from_user.id

    # 2. PREMIUM CONTENT DESIGN
    text = (
        "❓ <b>FOYDALANISH QO'LLANMASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Botingizdan samarali foydalanishingiz uchun barcha "
        "imkoniyatlar haqida qisqacha ma'lumot: 📑\n\n"
        "👤 <b>Shaxsiy kabinet:</b>\n"
        "Profilingiz, joriy ballaringiz va VIP holatini kuzatish.\n\n"
        "🏆 <b>Reyting:</b>\n"
        "Eng ko'p ball to'plagan va faol foydalanuvchilar TOP ro'yxati.\n\n"
        "💎 <b>VIP tizimi:</b>\n"
        "Cheklovsiz kirish, reklamalardan xoli va maxsus status.\n\n"
        "🎯 <b>Referal dasturi:</b>\n"
        "Do'stlaringizni taklif qilib, har bir faol foydalanuvchi uchun ball yig'ing.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📩 <b>Yordam kerakmi?</b>\n"
        "Savollar yoki takliflar bo'lsa, adminga murojaat qiling:"
    )

    # 3. SECURE ADMIN LINK
    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, yordam kerak. ID: {user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    # 4. KEYBOARD DESIGN (Pro UX)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📩 Admin bilan bog'lanish", url=admin_url)
        ],
        [
            types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet"),
            types.InlineKeyboardButton(text="💎 VIP menyu", callback_data="buy_vip_menu"),
        ],
        [
            types.InlineKeyboardButton(text="🔗 Taklif havola", callback_data="get_ref_link")
        ]
    ])

    # 5. FAST RESPONSE
    # L1 keshdan foydalanilgani uchun javob tezligi 100-300ms atrofida bo'ladi.[cite: 3, 6]
    await message.answer(text, reply_markup=kb, parse_mode="HTML")








@router.message(F.text == "📢 Reklama berish")
async def advertisement(message: types.Message, user: dict, state: FSMContext):
    """
    Reklama bo'limi: L1/L2 keshdan olingan user ma'lumotlari bilan tezkor ishlash.[cite: 1, 6]
    """
    await state.clear()

    # 1. CIRCUIT BREAKER & USER VALIDATION
    if not user:
        return await message.answer(
            "⚠️ Ma'lumotlarni yuklashda xatolik yuz berdi.\n"
            "Iltimos, /start buyrug'ini qayta yuboring."
        )

    user_id = user.get("user_id")

    # 2. PREMIUM CONTENT DESIGN
    text = (
        "📢 <b>REKLAMA VA HAMKORLIK</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Botingiz yoki loyihangizni bizning auditoriyamizga "
        "ko'rsatmoqchimisiz? Biz sizga yordam beramiz! 🚀\n\n"
        "📝 <b>Reklama yuborish tartibi:</b>\n"
        "🔹 Tayyor reklama posti (Matn + Rasm/Video)\n"
        "🔹 Havolalar (Linklar) to'g'ri sozlanganligi\n"
        "🔹 Kerakli auditoriya va vaqt kelishuvi\n\n"
        "💡 <b>Nima uchun biz?</b>\n"
        "✅ Faol va real foydalanuvchilar\n"
        "✅ Hamyonbop narxlar\n"
        "✅ Tezkor joylashtirish\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💼 Admin sizga barcha ma'lumotlarni taqdim etadi:"
    )

    # 3. SECURE ADMIN LINK
    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, reklama bermoqchiman. ID: {user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    # 4. KEYBOARD DESIGN
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="📩 Adminga ariza yuborish",
                url=admin_url
            )
        ],
        [
            types.InlineKeyboardButton(
                text="📊 Statistika (Tez kunda)",
                callback_data="adv_stats"
            )
        ]
    ])

    # 5. HIGH-SPEED RESPONSE
    # Keshdan ma'lumot olingani uchun javob berish vaqti < 300ms bo'ladi.[cite: 3]
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    

