from datetime import datetime, timezone
from aiogram import types, F, Router
from typing import Any  # ✅ To'g'risi shu
from flask import logging
from sqlalchemy import select, desc
from database.models import DBUser
from sqlalchemy.ext.asyncio import AsyncSession
from config import config
router = Router()
logger = logging.getLogger(__name__)

now = datetime.now(timezone.utc)
Creator_ID = getattr(config, 'CREATOR_ID', None)



@router.message(F.text == "👤 Shaxsiy kabinet")
async def personal_cabinet(message: types.Message, user: Any):
    # Xavfsiz olish
    user_id = getattr(user, 'user_id', message.from_user.id)
    points = getattr(user, 'points', 0)
    status = getattr(user, 'status', 'user')
    ref_count = getattr(user, 'referral_count', 0)
    vip_expire = getattr(user, 'vip_expire_date', None)
    
    # VIP status hisoblash (UTC bilan)
    now = datetime.now(timezone.utc)
    if vip_expire:
        # Bazadan kelgan vaqtni UTC ga moslash
        if vip_expire.tzinfo is None:
            vip_expire = vip_expire.replace(tzinfo=timezone.utc)
            
        if vip_expire > now:
            vip_status = f"✅ {vip_expire.strftime('%d.%m.%Y')} gacha"
        else:
            vip_status = "⚠️ Muddati tugagan"
    else:
        vip_status = "❌ Faol emas"

    # Username
    display_username = f"@{message.from_user.username}" if message.from_user.username else "O'rnatilmagan"

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
    
    # Tugmalar (UX uchun)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💎 VIP sotib olish", callback_data="buy_vip")],
        [types.InlineKeyboardButton(text="🔗 Taklif havola", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="👤 Saytdagi profilim", url="https://aninovuz.uz/profile")]
        
    ])

    try:
        await message.answer(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Cabinet error for user {user_id}: {e}", exc_info=True)


@router.message(F.text == "🌟 Reyting")
async def rating(message: types.Message, session: AsyncSession, user: DBUser):
    # 1. Bazadan TOP 10 ni olamiz
    stmt = select(DBUser).order_by(DBUser.points.desc()).limit(10)
    result = await session.execute(stmt)
    top_users = result.scalars().all()

    if not top_users:
        return await message.answer("📭 Reyting hozircha bo'sh.")

    text = "🏆 <b>TOP-10 Foydalanuvchilar:</b>\n\n"
    
    for i, top_user in enumerate(top_users, 1):
        # Username tekshiruvi: Agar bazada @Yo'q bo'lsa, ID ko'rsatiladi
        if top_user.username and top_user.username != "Yo'q":
            user_name = f"@{top_user.username}"
        else:
            user_name = f"ID:<code>{top_user.user_id}</code>"
            
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👤"
        text += f"{medal} {i}. {user_name} — <b>{top_user.points} ball</b>\n"

    # O'z ballingiz (Middleware orqali kelgan obyektni ishlatamiz)
    my_points = user.points if user.points is not None else 0
    text += f"\n\nSizning ballaringiz: <b>{my_points} ball</b>"
    
    await message.answer(text)


@router.message(F.text == "❓ Qo'llanma")
async def help_page(message: types.Message):
    text = (
        "❓ <b>Qo'llanma</b>\n\n"
        "🔍 <b>Anime qidirish</b> — anime nomini yozing\n"
        "👤 <b>Shaxsiy kabinet</b> — profilingizni ko'ring\n"
        "🌟 <b>Reyting</b> — eng mashhur animalar\n"
        "💎 <b>VIP</b> — maxsus imkoniyatlar\n\n"
        "Savollar uchun: @admin"
    )
    await message.answer(text)


@router.message(F.text == "💎 VIP sotib olish")
async def buy_vip(message: types.Message, user: DBUser, session: AsyncSession = None):
    """
    VIP menyusi: Foydalanuvchi statusini tekshiradi va takliflarni ko'rsatadi.
    """
    # 1. Baza holatini tekshirish (Circuit Breaker xavfsizligi)
    if session is None or user is None:
        return await message.answer(
            "⚠️ <b>VIP tizimi vaqtincha faol emas.</b>\n"
            "Texnik ishlar olib borilmoqda, birozdan so'ng urinib ko'ring."
        )

    # 2. Foydalanuvchining hozirgi statusiga qarab matn tayyorlash
    status_text = "✨ Sizning status: <b>VIP</b>" if user.is_vip else "🌑 Sizning status: <b>Oddiy foydalanuvchi</b>"
    
    text = (
        f"💎 <b>VIP REJIM</b>\n\n"
        f"{status_text}\n\n"
        f"<b>VIP imkoniyatlari:</b>\n"
        f"✅ Reklamasiz va cheklovsiz ko'rish\n"
        f"✅ Barcha yopiq kanallarga kirish\n"
        f"✅ Maxsus va pre-reliz kontentlar\n"
        f"✅ Tezkor yuklab olish tezligi\n\n"
        f"⏳ <b>To'lov tizimi tez kunda ishga tushadi!</b>"
    )

    await message.answer(text)

@router.message(F.text == "📢 Reklama berish")
async def advertisement(message: types.Message):
    await message.answer("📢Reklama xizmati tez kunda...")


