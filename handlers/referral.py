from flask import session
import pytz
import logging
import asyncio
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from datetime import datetime, timedelta, timezone
from services.orchestrator import state # Cache state'ni import qilish
from database.cache import valkey
from database.models import Channel, DBUser 
from handlers import user
from keyboards.reply import get_main_menu
from config import config
from handlers.user import personal_cabinet
from middlewares.db_middleware import DbSessionMiddleware
from main import get_now
logger = logging.getLogger("StartHandler")
router = Router()

# Shaxsiy kabinet ichidagi callback handler (get_ref_link uchun)
@router.callback_query(F.data == "get_ref_link")
async def get_ref_link_callback(callback: types.CallbackQuery, user: DBUser):
    # Bot username'ni dinamik olish
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.user_id}"
    
    text = (
        "<b>🔗 DO'STLARINGIZNI TAKLIF QILING</b>\n\n"
        "Har bir muvaffaqiyatli taklif uchun <b>10 ball</b> olasiz!\n\n"
        f"📎 Sizning havolangiz:\n<code>{ref_link}</code>\n\n"
        "👆 <i>Nusxalash uchun havola ustiga bosing.</i>"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="🚀 Do'stlarga ulashish", 
            switch_inline_query=f"\nAnime ko'rish uchun eng zo'r bot! 👇\n{ref_link}"
        )],
        [types.InlineKeyboardButton(text="📊 Takliflarim", callback_data="check_referrals")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_cabinet")]
    ])
    
    # edit_text ishlatganda try-except qo'yish yaxshi amaliyot (matn o'zgarmasa xato bermasligi uchun)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "check_referrals")
async def check_referrals_callback(callback: types.CallbackQuery, user: DBUser, session: AsyncSession):
    # Taklif qilingan foydalanuvchilar sonini olish
    result = await session.execute(
        select(func.count()).select_from(DBUser).where(DBUser.referred_by == user.user_id)
    )
    referral_count = result.scalar() or 0

    text = (
        f"<b>📊 SIZNING TAKLIFLARINGIZ</b>\n\n"
        f"Siz {referral_count} ta do'stingizni taklif qilgansiz!\n\n"
        f"Sizning ballaringiz: <b>{user.points}</b>\n\n"
        "Har bir muvaffaqiyatli taklif uchun <b>10 ball</b> olasiz!"
        f"\n\n<i>Do'stlaringizni taklif qilishni davom ettiring va ko'proq ball to'plang! va 100 ball yig'sangiz 30 kunlik vip pass  olasiz</i>"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=" VIP'ga almashtirish ", callback_data="exchange_points")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="get_ref_link")]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "back_to_cabinet")
async def back_to_cabinet(callback: types.CallbackQuery, user: DBUser):
    # Funksiya ichida import qilish circular import'dan qutqaradi
    from handlers.user import personal_cabinet 
    await personal_cabinet(callback, user)
    await callback.answer()

@router.callback_query(F.data == "exchange_points")
async def exchange_points_handler(callback: types.CallbackQuery, user: DBUser, session: AsyncSession):
    uzb_tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(uzb_tz)
    # 1. Ballarni tekshirish
    if user.points < 100:
        needed = 100 - user.points
        text = (
            f"⚠️ <b>KECHIRASIZ, BALLARINGIZ YETARLI EMAS!</b>\n\n"
            f"VIP pass olish uchun 100 ball kerak. Sizda hozir <b>{user.points}</b> ball bor.\n"
            f"Yana <b>{needed}</b> ball to'plashingiz kerak.\n\n"
            f"💡 <i>Do'stlaringizga referal havolangizni yuboring va ballar yig'ing!</i>"
        )
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔙 Orqaga qaytish", callback_data="check_referrals")]
        ])
        
        # Xabarni tahrirlaymiz va orqaga tugmasini qo'shamiz
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return await callback.answer() # "Clock" iconni yo'qotish uchun

    try:
        # 2. VIP muddatini hisoblash
        if user.vip_expire_date:
            # Bazadan kelgan vaqtga Toshkent mintaqasini biriktiramiz
            if user.vip_expire_date.tzinfo is None:
                current_vip_end = uzb_tz.localize(user.vip_expire_date)
            else:
                current_vip_end = user.vip_expire_date.astimezone(uzb_tz)

            
            if current_vip_end > now:
                user.vip_expire_date = current_vip_end + timedelta(days=30)
            else:
                user.vip_expire_date = now + timedelta(days=30)
        else:
           
            user.vip_expire_date = now + timedelta(days=30)

        # 3. Bazani yangilash
        user.points -= 100
        user.status = "vip"
        # Agar bazada timezone xatosi chiqsa, buni ishlating:
        user.vip_expire_date = user.vip_expire_date.replace(tzinfo=None)
        await session.commit()
        await session.refresh(user)

        # Keshni tozalash
        if hasattr(state, 'l1_cache'):
            state.l1_cache.pop(user.user_id, None)
        if valkey.is_alive:
            await valkey.delete("db_users", user.user_id)

        await callback.answer("🎉 VIP muvaffaqiyatli faollashtirildi!", show_alert=True)
        
        # Shaxsiy kabinetni yangilab ko'rsatish
        from handlers.user import personal_cabinet
        await personal_cabinet(callback, user)

    except Exception as e:
        await session.rollback()
        logger.error(f"Exchange error: {e}")
        await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)


