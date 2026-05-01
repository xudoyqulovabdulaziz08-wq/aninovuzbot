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
router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)



@router.message(F.text == "👤 Shaxsiy kabinet")
async def personal_cabinet(message: Union[types.Message, types.CallbackQuery], user: DBUser, state: FSMContext):
    await state.clear()
    target = message.message if isinstance(message, types.CallbackQuery) else message
    
    # Toshkent vaqt mintaqasi
    uzb_tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(uzb_tz)

    user_id = user.user_id
    points = user.points
    status = user.status
    ref_count = user.referral_count
    vip_expire = user.vip_expire_date
    
    # VIP status hisoblash
    if vip_expire:
        # 1. Bazadan kelgan vaqtni Toshkent vaqtiga moslaymiz
        if vip_expire.tzinfo is None:
            # Agar bazada timezone saqlanmagan bo'lsa, uni Toshkent vaqti deb qabul qilamiz
            ve_aware = uzb_tz.localize(vip_expire)
        else:
            # Agar timezone bo'lsa, uni Toshkent vaqtiga o'giramiz
            ve_aware = vip_expire.astimezone(uzb_tz)
            
        # 2. Solishtirish
        if ve_aware > now:
            vip_status = f"✅ {ve_aware.strftime('%d.%m.%Y | %H:%M')} gacha"
        else:
            vip_status = "⚠️ Muddati tugagan"
    else:
        vip_status = "❌ Faol emas"

    # Username (target xabardan emas, messagedan olingani ma'qul)
    user_info = message.from_user if isinstance(message, types.Message) else message.from_user
    display_username = f"@{user_info.username}" if user_info.username else "O'rnatilmagan"

    text = (
        f"👤 <b>SHAXSIY KABINET</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Username: {display_username}\n"
        f"🏅 Status: <b>{status.upper()}</b>\n"
        f"⭐ Ballar: <b>{points}</b>\n"
        f"👥 Takliflar: <b>{ref_count}</b> ta\n"
        f"💎 VIP: <b>{vip_status}</b>\n"
        f"━━━━━━━━━━━━━━"
    )
    
    kb_list = [
        [types.InlineKeyboardButton(text="💎 VIP sotib olish", callback_data="buy_vip_menu")],
        [types.InlineKeyboardButton(text="🔗 Taklif havola", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="👤 Saytdagi profilim", url="https://aninowuz.uz/profile")]
    ]
    
    # 💡 Agar ballar yetsa, ballarni almashtirish tugmasini ham shu yerda ko'rsatish mumkin
    if points >= 100:
        kb_list.insert(0, [types.InlineKeyboardButton(text="💎 Ballarni VIP'ga almashtirish", callback_data="exchange_points")])

    kb = types.InlineKeyboardMarkup(inline_keyboard=kb_list)

    try:
        # Agar bu callback bo'lsa (ya'ni almashtirishdan keyin chaqirilsa) - EDIT qilamiz
        if isinstance(message, types.CallbackQuery):
            await message.message.edit_text(text, reply_markup=kb)
        else:
            # Agar oddiy matnli xabar bo'lsa - yangi xabar yuboramiz
            await message.answer(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Cabinet error: {e}")





@router.message(F.text == "❓ Qo'llanma")
async def help_page(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "❓ <b>QO‘LLANMA</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "📌 <b>Bot imkoniyatlari:</b>\n\n"
        "👤 Shaxsiy kabinet — profil va VIP\n"
        "🏆 Reyting — TOP foydalanuvchilar\n"
        "💎 VIP tizimi — maxsus imkoniyatlar\n"
        "🎯 Referal — do‘st taklif qilib ball yig‘ish\n\n"
        "📩 Savollar bo‘lsa admin bilan bog‘laning"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="📩 Admin bilan bog‘lanish",
                url="https://t.me/Khudoyqulov_pg"
            )
        ],
        [
            types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet"),
            types.InlineKeyboardButton(text="💎 VIP", callback_data="buy_vip_menu"),
        ]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML")






@router.message(F.text == "📢 Reklama berish")
async def advertisement(message: types.Message, user: DBUser, state: FSMContext):
    await state.clear()
    text = (
        "📢 <b>REKLAMA BO‘LIMI</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "📌 Reklama yuborish tartibi:\n\n"
        "📝 Matn\n"
        "🎥 Rasm yoki video\n"
        "🎯 Auditoriya (ixtiyoriy)\n\n"
        "💡 <b>Misol:</b>\n"
        "• Nima reklama\n"
        "• Kimlar uchun\n"
        "• Qachon\n\n"
        "👨‍💼 Admin siz bilan bog‘lanadi"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="📩 Admin bilan bog‘lanish",
                url="https://t.me/Khudoyqulov_pg"
            )
        ]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    

