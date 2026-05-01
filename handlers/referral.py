
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
from aiogram.exceptions import TelegramBadRequest


logger = logging.getLogger("StartHandler")
router = Router()

# Shaxsiy kabinet ichidagi callback handler (get_ref_link uchun)
@router.callback_query(F.data == "get_ref_link")
async def get_ref_link_callback(callback: types.CallbackQuery, user: DBUser):
    # User obyektini tekshirish (Middleware xavfsizligi)
    if user is None:
        return await callback.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)

    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.user_id}"

    # Statistikani olish (user obyekti middleware orqali kelyapti)
    current_points = getattr(user, 'points', 0)
    current_refs = getattr(user, 'referral_count', 0)

    text = (
        "<b>🔗 DO'STLARINGIZNI TAKLIF QILING</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 Taklif qilgan do'stlaringiz: <b>{current_refs} ta</b>\n"
        f"💰 Sizning ballaringiz: <b>{current_points} ball</b>\n\n"
        "🎁 <b>Bonus tizimi:</b>\n"
        "🔥 Har bir do‘st = <b>10 ball</b>\n"
        "💎 100 ball to'plab 1 oy VIP oling!\n\n"
        f"📎 Sizning havolangiz:\n<code>{ref_link}</code>\n\n"
        "📌 <i>Nusxalash uchun havola ustiga bosing</i>"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="🚀 Do'stlarga ulashish",
                switch_inline_query=f"\nAnime ko‘rish uchun eng zo‘r bot! Hoziroq qo'shiling: {ref_link}"
            )
        ],
        [
            types.InlineKeyboardButton(text="📊 Takliflarim ro'yxati", callback_data="check_referrals")
        ],
        [
            types.InlineKeyboardButton(text="👤 Shaxsiy kabinet", callback_data="back_to_cabinet")
        ],
        [
            types.InlineKeyboardButton(text="💎 VIP sotib olish", callback_data="buy_vip_menu")
        ]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            if "message can't be edited" in str(e).lower():
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            else:
                raise

    await callback.answer()

@router.callback_query(F.data == "check_referrals")
async def check_referrals_callback(callback: types.CallbackQuery, user: DBUser, session: AsyncSession):
    if session is None:
        return await callback.answer("⚠️ Baza bilan aloqa yo'q.", show_alert=True)

    # Eng aniq sonni olish uchun count query (Siz yozganingizdek)
    stmt = select(func.count(DBUser.user_id)).where(DBUser.referred_by == user.user_id)
    real_ref_count = (await session.execute(stmt)).scalar() or 0

    # Agar bazadagi referral_count bilan farq qilsa, uni yangilab qo'yish ham mumkin (ixtiyoriy)
    # user.referral_count = real_ref_count 

    text = (
        "<b>📊 SIZNING TAKLIFLARINGIZ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👥 Umumiy takliflar: <b>{real_ref_count} ta</b>\n"
        f"💰 Mavjud ballar: <b>{user.points} ball</b>\n\n"
        "💎 <b>Bonus:</b> 100 ball to'plab 30 kunlik VIP statusini bepul faollashtiring!\n\n"
        "🚀 <i>Ko'proq do'stlarni taklif qiling va imkoniyatlarni kengaytiring!</i>"
    )

    # Ballar yetarli bo'lsa tugmani boshqacha ko'rsatish (UX uchun)
    exchange_text = "💎 VIP ga almashtirish (100 ball)"
    if user.points >= 100:
        exchange_text = "✅ VIP ga almashtirish (TAYYOR)"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=exchange_text, callback_data="exchange_points")], # Avvalgi buy_vip_points handleriga yo'naltiramiz
        [types.InlineKeyboardButton(text="🔗 Taklif havolasi", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="👤 Shaxsiy kabinet", callback_data="back_to_cabinet")]
        
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

    await callback.answer()



@router.callback_query(F.data == "back_to_cabinet")
async def back_to_cabinet(callback: types.CallbackQuery, user: DBUser):
    # Funksiya ichida import qilish circular import'dan qutqaradi
    from handlers.user import personal_cabinet 
    await personal_cabinet(callback, user)
    await callback.answer()

@router.callback_query(F.data == "exchange_points")
async def exchange_points(callback: types.CallbackQuery, user: DBUser, session: AsyncSession):
    # 0. Session xavfsizligi
    if session is None:
        return await callback.answer("⚠️ Baza bilan aloqa yo'q.", show_alert=True)

    now = datetime.now(timezone.utc)

    # 1. Ballarni tekshirish
    if user.points < 100:
        needed = 100 - user.points
        text = (
            "⚠️ <b>BALL YETARLI EMAS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Sizda: <b>{user.points} ball</b>\n"
            f"Kerak: <b>{needed} ball</b>\n\n"
            "💡 Do‘stlarni taklif qilib ball yig‘ing yoki VIP sotib oling!"
        )

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📊 Takliflarim ro'yxati", callback_data="check_referrals")],
            [types.InlineKeyboardButton(text="💳 VIP sotib olish", callback_data="buy_vip_start")],
            [types.InlineKeyboardButton(text="👤 Kabinet", callback_data="back_to_cabinet")]
        ])

        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return await callback.answer()

    try:
        # 2. VIP vaqtini hisoblash (Stacking logic)
        # Ma'lumotlar bazasidagi vaqtni UTC aware qilish (xatolikni oldini olish uchun)
        expire_date = user.vip_expire_date
        if expire_date and expire_date.tzinfo is None:
            expire_date = expire_date.replace(tzinfo=timezone.utc)

        base = expire_date if expire_date and expire_date > now else now
        user.vip_expire_date = base + timedelta(days=30)

        # 3. Ballarni yechish va statusni yangilash
        user.points -= 100
        user.status = "vip"

        # 4. Saqlash
        await session.commit()

        await callback.answer(
            "🎉 VIP faollashtirildi! Muddat 30 kunga uzaytirildi 👑",
            show_alert=True
        )

        # 5. Kabinetni yangilab ko'rsatish
        from handlers.user import personal_cabinet
        await personal_cabinet(callback, user, session)

    except Exception as e:
        await session.rollback()
        # logger obyektini import qilganingizga ishonch hosil qiling
        print(f"Xatolik yuz berdi: {e}") 
        await callback.answer("❌ Amaliyot bajarilmadi. Keyinroq urinib ko'ring.", show_alert=True)

