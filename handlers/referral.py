
import html
import pytz
import logging
import asyncio
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import func, select
from datetime import datetime, timedelta, timezone
from services.orchestrator import state # Cache state'ni import qilish
from database.cache import valkey
from database.models import Channel, DBUser

from handlers import user
from keyboards.reply import get_main_menu
from config import config
from typing import Any
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
async def check_referrals_callback(callback: types.CallbackQuery, user: dict, session: Any, session_pool: async_sessionmaker):
    """
    Referral tekshirish: Kesh va Bazani aqlli sinxronizatsiya qilish.
    """
    user_id = user.get("user_id")
    
    # 1. LAZY SESSION: Agar middleware sessiya bermagan bo'lsa, yangisini ochamiz[cite: 15, 17]
    # Bu SafeSession(None) holatida RuntimeError'ni oldini oladi.
    actual_session = session._session if hasattr(session, "_session") else session
    
    # Agar keshdan kelgan bo'lsa, actual_session None bo'ladi
    session_is_external = actual_session is not None
    
    try:
        if not session_is_external:
            # Yangi sessiya yaratamiz
            async with session_pool() as new_session:
                real_ref_count = await _get_ref_count(new_session, user_id)
        else:
            real_ref_count = await _get_ref_count(actual_session, user_id)

        # 2. KESHNI YANGILASH MANTIQI
        if user.get("referral_count") != real_ref_count:
            user["referral_count"] = real_ref_count # Local dict update
            
            # Orchestrator orqali keshni tozalash
            from services.orchestrator import state
            async with state.db_lock:
                state.l1_cache.pop(user_id, None)
            await valkey.delete("db_users", user_id)

        # 3. UI/UX QISMI
        await render_referral_ui(callback, user, real_ref_count)

    except Exception as e:
        logger.error(f"Referral logic error: {e}")
        await callback.answer("⚠️ Ma'lumotlarni yangilashda xatolik.", show_alert=True)

async def _get_ref_count(session: AsyncSession, user_id: int) -> int:
    """Bazadan referral sonini xavfsiz olish[cite: 16]."""
    stmt = select(func.count(DBUser.user_id)).where(DBUser.referred_by == user_id)
    result = await session.execute(stmt)
    return result.scalar() or 0

async def render_referral_ui(callback: types.CallbackQuery, user: dict, ref_count: int):
    """Chiroyli interfeysni render qilish."""
    points = user.get("points", 0)
    bar_filled = min(points // 10, 10)
    progress_bar = "🟦" * bar_filled + "⬜" * (10 - bar_filled)
    
    text = (
        "<b>📊 REFERRAL STATISTIKASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Foydalanuvchi: <b>{html.escape(callback.from_user.full_name)}</b>\n"
        f"👥 Takliflar: <b>{ref_count} ta</b>\n"
        f"💰 Ballar: <b>{points} ball</b>\n\n"
        f"🏆 <b>VIP Progress:</b> ({points}/100)\n"
        f"{progress_bar}\n\n"
        "🚀 <i>100 ball to'plab VIP statusiga ega bo'ling!</i>"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💎 VIP ga almashtirish", callback_data="exchange_points")],
        [types.InlineKeyboardButton(text="🔗 Taklif havolasi", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="cabinet")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()










@router.callback_query(F.data == "exchange_points")
async def exchange_points(callback: types.CallbackQuery, user: dict, session: Any, state_fsm: FSMContext, session_pool: async_sessionmaker):
    """
    VIP almashtirish: Lazy session va xavfsiz stacking mantiqi.
    """
    user_id = user.get("user_id")
    
    # 1. LAZY SESSION & CIRCUIT BREAKER
    # Agar middleware sessiya bermagan bo'lsa (keshdan kelgan), yangisini ochamiz.
    actual_session = session._session if hasattr(session, "_session") else session
    
    try:
        # Sessiya boshqaruvini xavfsiz blok ichiga olamiz
        if actual_session is None:
            async with session_pool() as new_session:
                return await _process_exchange(callback, user_id, new_session, state_fsm)
        else:
            return await _process_exchange(callback, user_id, actual_session, state_fsm)

    except Exception as e:
        print(f"🚨 Exchange Critical Error: {e}")
        await callback.answer("❌ Tizimda texnik nosozlik (DB_ERR)", show_alert=True)

async def _process_exchange(callback, user_id, session, state_fsm):
    """Asosiy almashtirish jarayoni - Tranzaksiya xavfsizligi bilan."""
    try:
        # 2. REAL-TIME DB CHECK (Zararli o'zgarishlardan himoya)
        db_user = await session.get(DBUser, user_id)
        if not db_user:
            return await callback.answer("❌ Foydalanuvchi ma'lumotlari topilmadi.", show_alert=True)

        # 3. BALLARNI TEKSHIRISH
        REQUIRED_POINTS = 100
        if db_user.points < REQUIRED_POINTS:
            needed = REQUIRED_POINTS - db_user.points
            
            # UX: Progress bar ko'rinishida yetishmayotgan ballarni ko'rsatish
            filled = int((db_user.points / REQUIRED_POINTS) * 10)
            bar = "🟦" * filled + "⬜" * (10 - filled)
            
            text = (
                "⚠️ <b>BALLARINGIZ YETARLI EMAS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Sizda: <b>{db_user.points} ball</b> ✨\n"
                f"Progress: [{bar}] <b>{db_user.points}%</b>\n\n"
                f"🚀 VIP uchun yana <b>{needed} ball</b> kerak.\n\n"
                "💡 <i>Do'stlarni taklif qilish orqali ball yig'ing!</i>"
            )
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔗 Do'stlarni taklif qilish", callback_data="get_ref_link")],
                [types.InlineKeyboardButton(text="🔙 Kabinetga qaytish", callback_data="cabinet")]
            ])
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return await callback.answer("Ballar yetarli emas ⚠️")

        # 4. VIP STACKING LOGIC (Vaqtni to'g'ri hisoblash)
        now = datetime.now(timezone.utc)
        expire_date = db_user.vip_expire_date
        
        # Datetime obyektini timezone-aware qilish
        if expire_date and expire_date.tzinfo is None:
            expire_date = expire_date.replace(tzinfo=timezone.utc)

        # Agar hozirgi VIP muddati o'tmagan bo'lsa, uning ustiga qo'shamiz
        base_time = expire_date if expire_date and expire_date > now else now
        db_user.vip_expire_date = base_time + timedelta(days=30)
        db_user.points -= REQUIRED_POINTS
        db_user.status = "vip"

        # 5. DB COMMIT (Ma'lumotlarni saqlash)
        await session.commit()

        # 6. CACHE INVALIDATION (L1 va L2 keshni tozalash)
        from services.orchestrator import state
        async with state.db_lock:
            state.l1_cache.pop(user_id, None)
        await valkey.delete("db_users", user_id)

        # 7. SUCCESS UX
        await callback.answer("🎉 TABRIKLAYMIZ!\nVIP status 30 kunga faollashtirildi! 👑", show_alert=True)

        # 8. YANGILANGAN KABINETNI KO'RSATISH
        updated_dict = {
            "user_id": db_user.user_id,
            "username": db_user.username,
            "status": db_user.status,
            "points": db_user.points,
            "referral_count": db_user.referral_count,
            "is_vip": True,
            "vip_expire_date": db_user.vip_expire_date.timestamp()
        }
        
        from handlers.user import personal_cabinet
        await personal_cabinet(callback, updated_dict, state_fsm)

    except Exception as e:
        await session.rollback() # Xatolik bo'lsa tranzaksiyani bekor qilish
        raise e