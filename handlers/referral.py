
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
from aiogram.fsm.context import FSMContext


logger = logging.getLogger("ExchangeHandler")
router = Router()





@router.callback_query(F.data == "get_ref_link")
async def get_ref_link_callback(callback: types.CallbackQuery, user: dict, state: FSMContext):
    """
    Referal tizimi: Keshdan olingan ma'lumotlar bilan bazaga yuklamasiz ishlaydi.[cite: 1, 3]
    """
    await state.clear()
    
    # 1. USER & CIRCUIT BREAKER VALIDATION
    if not user:
        return await callback.answer(
            "⚠️ Ma'lumot topilmadi. Qayta /start bosing.", 
            show_alert=True
        )

    # 2. DATA PARSING (Middleware keshidan kelgan dict)[cite: 1, 6]
    user_id = user.get("user_id")
    current_points = user.get("points", 0)
    current_refs = user.get("referral_count", 0)

    # Bot ma'lumotlarini keshdan olish (Performance optimizatsiyasi)
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    # 3. PREMIUM UI DESIGN
    text = (
        "<b>🔗 DO'STLARINGIZNI TAKLIF QILING</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Takliflar: <b>{current_refs} ta</b>\n"
        f"💰 Balansingiz: <b>{current_points} ball</b>\n\n"
        "🎁 <b>Bonus tizimi:</b>\n"
        "🔥 Har bir faol do‘st uchun = <b>10 ball</b>\n"
        "💎 100 ball to'plab 30 kunlik VIP oling!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 <b>Sizning shaxsiy havolangiz:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "📌 <i>Nusxalash uchun havola ustiga bir marta bosing.</i>"
    )

    # 4. KEYBOARD DESIGN (Interactive UX)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="🚀 Do'stlarga yuborish",
                switch_inline_query=f"\nAnime ko‘rish uchun eng zo‘r bot! Hoziroq qo'shiling: {ref_link}"
            )
        ],
        [
            types.InlineKeyboardButton(text="👤 Shaxsiy kabinet", callback_data="cabinet"),
            types.InlineKeyboardButton(text="💎 VIP menyu", callback_data="buy_vip_menu")
        ],
        [
            types.InlineKeyboardButton(text="💫 Takliflarim", callback_data="check_referrals")
        ]
    ])

    # 5. SAFE & FAST RESPONSE
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            await callback.answer()
        elif "message can't be edited" in err_msg:
            # Agar xabarni edit qilib bo'lmasa, yangisini yuborib eskisini o'chiramiz
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            await callback.message.delete()
        else:
            raise e

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

  
    

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💎 VIP ga almashtirish (100 ball)", callback_data="exchange_points")], # Avvalgi buy_vip_points handleriga yo'naltiramiz
        [types.InlineKeyboardButton(text="🔗 Taklif havolasi", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="👤 Shaxsiy kabinet", callback_data="cabinet")]
        
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

    await callback.answer()











@router.callback_query(F.data == "exchange_points")
async def exchange_points(callback: types.CallbackQuery, user: dict, session: AsyncSession, state_fsm: FSMContext):
    """
    Ballarni VIP'ga almashtirish: Outbox pattern va L1/L2 kesh integratsiyasi.[cite: 15, 17, 20]
    """
    # 1. CIRCUIT BREAKER & SESSION CHECK
    if not user or isinstance(session, type(None)):
        return await callback.answer("⚠️ Tizim vaqtincha offline. Keyinroq urinib ko'ring.", show_alert=True)

    user_id = user.get("user_id")

    try:
        # 2. REAL-TIME DB CHECK (Keshdan emas, bazadan olish shart)
        db_user = await session.get(DBUser, user_id)
        if not db_user:
            return await callback.answer("❌ Foydalanuvchi topilmadi.", show_alert=True)

        # 3. BALLARNI TEKSHIRISH
        if db_user.points < 100:
            needed = 100 - db_user.points
            text = (
                "⚠️ <b>BALLARINGIZ YETARLI EMAS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Sizda: <b>{db_user.points} ball</b> ✨\n"
                f"Yana <b>{needed} ball</b> kerak. 🚀\n\n"
                "💡 <i>Do'stlarni taklif qiling va ballar to'plang!</i>"
            )
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🚀 Ball yig'ish", callback_data="get_ref_link")],
                [types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet")]
            ])
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return await callback.answer()

        # 4. VIP STACKING LOGIC (ORM LEVEL)[cite: 15, 16]
        now = datetime.now(timezone.utc)
        expire_date = db_user.vip_expire_date
        
        # Vaqtni UTC formatga keltirish
        if expire_date and expire_date.tzinfo is None:
            expire_date = expire_date.replace(tzinfo=timezone.utc)

        base_time = expire_date if expire_date and expire_date > now else now
        db_user.vip_expire_date = base_time + timedelta(days=30)
        db_user.points -= 100
        db_user.status = "vip"

        # 5. DB COMMIT & OUTBOX TRIGGER
        # SQLAlchemy 'after_update' listeneri OutboxEvent yaratadi va keshni invalidatsiya qiladi
        await session.commit()

        # 6. INSTANT CACHE INVALIDATION (L1 dan darhol o'chirish)[cite: 11, 19]
        from services.orchestrator import state
        async with state.db_lock:
            state.l1_cache.pop(user_id, None) # L1 keshni tozalash
        
        # L2 (Valkey) keshni o'chirish[cite: 11]
        await valkey.delete("db_users", user_id)

        # 7. SUCCESS UX
        await callback.answer(
            "🎉 TABRIKLAYMIZ!\nVIP status 30 kunga faollashtirildi! 👑", 
            show_alert=True
        )

        # 8. REFRESH CABINET[cite: 17]
        # Yangilangan ma'lumotlarni dict ko'rinishida shakllantirish
        updated_user = {
            "user_id": db_user.user_id,
            "username": db_user.username,
            "status": db_user.status,
            "points": db_user.points,
            "referral_count": db_user.referral_count,
            "is_vip": True,
            "vip_expire_date": db_user.vip_expire_date.timestamp()
        }
        
        from handlers.user import personal_cabinet
        await personal_cabinet(callback, updated_user, state_fsm)

    except Exception as e:
        await session.rollback()
        logger.error(f"Exchange points error for {user_id}: {e}")
        await callback.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko'ring.", show_alert=True)

