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

# handlers/referral.py ichida

@router.callback_query(F.data == "back_to_cabinet")
async def back_to_cabinet(callback: types.CallbackQuery, user: DBUser):
    # Funksiya ichida import qilish circular import'dan qutqaradi
    from handlers.user import personal_cabinet 
    await personal_cabinet(callback, user)
    await callback.answer()

@router.callback_query(F.data == "exchange_points")
async def exchange_points_handler(callback: types.CallbackQuery, user: DBUser, session: AsyncSession):
    if user.points < 100:
        return await callback.answer(
            "⚠️ Sizda yetarli ballar yo'q. VIP olish uchun kamida 100 ball to'plashingiz kerak.", 
            show_alert=True
        )

    try:
        # 1. Ma'lumotlarni yangilash
        user.points -= 100
        user.status = "vip"
        
        now = datetime.now(timezone.utc)
        
        if user.vip_expire_date and user.vip_expire_date.replace(tzinfo=timezone.utc) > now:
            user.vip_expire_date += timedelta(days=30)
        else:
            user.vip_expire_date = now + timedelta(days=30)

        # 2. BAZAGA SAQLASH
        await session.commit()
        # Obyektni yangilangan holatda ushlab turish uchun
        await session.refresh(user)

        # 3. KESHNI TOZALASH
        if hasattr(state, 'l1_cache'):
            state.l1_cache.pop(user.user_id, None)
        
        if valkey.is_alive:
            await valkey.delete("db_users", user.user_id)

        # 4. Muvaffaqiyatli xabar (Alert)
        await callback.answer(
            "🎉 Tabriklaymiz! 100 ball muvaffaqiyatli 30 kunlik VIP obunaga almashtirildi.", 
            show_alert=True
        )
        
        # 5. KABINETNI YANGILASH
        # Bu yerda personal_cabinet funksiyasini chaqiramiz. 
        # U avtomatik ravishda yangi status va ballarni ko'rsatadi.
        await personal_cabinet(callback.message, user)

    except Exception as e:
        await session.rollback()
        logger.error(f"Exchange points error for user {user.user_id}: {e}")
        await callback.answer("❌ Xatolik yuz berdi. Iltimos keyinroq urinib ko'ring.", show_alert=True)


