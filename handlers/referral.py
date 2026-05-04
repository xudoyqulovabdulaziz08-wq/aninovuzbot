
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
async def check_referrals_callback(
    callback: types.CallbackQuery, 
    user: dict, 
    session: Any, 
    session_pool: async_sessionmaker # Endi middleware orqali aniq keladi
):
    """
    Referral tekshirish: Kesh va Bazani aqlli sinxronizatsiya qilish.
    """
    user_id = user.get("user_id")
    
    # 1. LAZY SESSION: SafeSession(None) holatida RuntimeError'ni oldini olish
    actual_session = session._session if hasattr(session, "_session") else session
    
    try:
        # Sessiya mavjudligiga qarab ishlatish
        if actual_session is None:
            async with session_pool() as new_session:
                real_ref_count = await _get_ref_count(new_session, user_id)
        else:
            real_ref_count = await _get_ref_count(actual_session, user_id)

        # 2. KESHNI YANGILASH (Faqat ma'lumot o'zgargan bo'lsa)
        if user.get("referral_count") != real_ref_count:
            user["referral_count"] = real_ref_count
            
            from services.orchestrator import state
            async with state.db_lock:
                state.l1_cache.pop(user_id, None)
            await valkey.delete("db_users", user_id)

        # 3. UI/UX QISMI
        await render_referral_ui(callback, user, real_ref_count)

    except Exception as e:
        logger.error(f"Referral logic error for {user_id}: {e}")
        await callback.answer("⚠️ Ma'lumotlarni yuklashda xatolik.", show_alert=True)

async def _get_ref_count(session: AsyncSession, user_id: int) -> int:
    """Bazadan referral sonini xavfsiz olish."""
    stmt = select(func.count(DBUser.user_id)).where(DBUser.referred_by == user_id)
    result = await session.execute(stmt)
    return result.scalar() or 0

async def render_referral_ui(callback: types.CallbackQuery, user: dict, ref_count: int):
    """Chiroyli va tushunarli interfeys."""
    points = user.get("points", 0)
    
    # Progress bar mantiqi (100 ballgacha)
    max_points = 100
    bar_filled = min(points // 10, 10)
    progress_bar = "🟦" * bar_filled + "⬜" * (10 - bar_filled)
    
    # Foizni hisoblash
    percent = min(int((points / max_points) * 100), 100)
    
    text = (
        "<b>📊 REFERRAL STATISTIKASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Foydalanuvchi: <b>{html.escape(callback.from_user.full_name)}</b>\n"
        f"👥 Umumiy takliflar: <b>{ref_count} ta</b>\n"
        f"💰 To'plangan ballar: <b>{points} ball</b>\n\n"
        f"🏆 <b>VIP Progress:</b> <code>{percent}%</code>\n"
        f"{progress_bar}\n"
        f"└ <i>Yana {max(0, max_points - points)} ball to'plab VIP oling!</i>\n\n"
        f" 100 ball = 30 kunlik vip💎"
        "🚀 <i>Do'stlarni taklif qilish orqali imkoniyatlarni kengaytiring!</i>"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💎 VIP ga almashtirish (100 ball)", callback_data="exchange_points")],
        [types.InlineKeyboardButton(text="🔗 Taklif havolasi", callback_data="get_ref_link")],
        [types.InlineKeyboardButton(text="🔙 Shaxsiy kabinet", callback_data="cabinet")]
    ])

    try:
        # Xabarni faqat o'zgargan bo'lsa yangilash (Telegram API xatosini oldini olish)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    
    await callback.answer()










logger = logging.getLogger(__name__)

@router.callback_query(F.data == "exchange_points")
async def exchange_points(
    callback: types.CallbackQuery, 
    user: dict, 
    session: Any, 
    state: FSMContext, 
    session_pool: async_sessionmaker # Endi bu xato bermaydi!
):
    """
    VIP almashtirish: Ma'lumotlar xavfsizligi va yuqori UX darajasi.
    """
    user_id = user.get("user_id")
    
    # 1. SESSION MANAGEMENT (Lazy Loading)
    # Middleware'dan kelgan SafeSession ichidagi haqiqiy sessiyani olamiz
    actual_session = session._session if hasattr(session, "_session") else session

    try:
        if actual_session is None:
            # Agar keshdan kelgan bo'lsa, pool'dan yangi sessiya ochamiz
            async with session_pool() as new_session:
                return await _execute_exchange_logic(callback, user_id, new_session, state)
        else:
            # Agar keshda bo'lmasa, mavjud sessiyadan foydalanamiz
            return await _execute_exchange_logic(callback, user_id, actual_session, state)

    except Exception as e:
        logger.error(f"🔥 Exchange Critical Error for {user_id}: {e}")
        await callback.answer("❌ Tizimda texnik xatolik yuz berdi.", show_alert=True)

async def _execute_exchange_logic(callback, user_id, session, state):
    """Asosiy almashtirish mantiqi va DB tranzaksiyasi."""
    try:
        # 2. REAL-TIME VALIDATION
        db_user = await session.get(DBUser, user_id)
        if not db_user:
            return await callback.answer("❌ Ma'lumotlar bazasidan profil topilmadi.", show_alert=True)

        # 3. BALLARNI TEKSHIRISH (UX Progress Bar bilan)
        REQUIRED = 100
        if db_user.points < REQUIRED:
            filled = int((db_user.points / REQUIRED) * 10)
            bar = "🟦" * filled + "⬜" * (10 - filled)
            
            text = (
                "⚠️ <b>BALLARINGIZ YETARLI EMAS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Sizda: <b>{db_user.points} ball</b> ✨\n"
                f"Progress: <code>[{bar}]</code> <b>{db_user.points}%</b>\n\n"
                f"🚀 VIP uchun yana <b>{REQUIRED - db_user.points} ball</b> kerak.\n\n"
                "💡 <i>Do'stlarni taklif qilish orqali ball yig'ing!</i>"
            )
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔗 Do'stlarni taklif qilish", callback_data="get_ref_link")],
                [types.InlineKeyboardButton(text="🔙 Kabinet", callback_data="cabinet")]
            ])
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return await callback.answer()

        # 4. VIP STACKING (Vaqtni to'g'ri qo'shish)
        now = datetime.now(timezone.utc)
        expire_date = db_user.vip_expire_date
        
        if expire_date and expire_date.tzinfo is None:
            expire_date = expire_date.replace(tzinfo=timezone.utc)

        base_time = expire_date if expire_date and expire_date > now else now
        db_user.vip_expire_date = base_time + timedelta(days=30)
        db_user.points -= REQUIRED
        db_user.status = "vip"

        # 5. ATOMIC COMMIT
        await session.commit()

        # 6. CACHE PURGE (L1 va L2 keshni yangilash)
        from services.orchestrator import state
        async with state.db_lock:
            state.l1_cache.pop(user_id, None)
        await valkey.delete("db_users", user_id)

        # 7. SUCCESS UX
        await callback.answer("🎉 TABRIKLAYMIZ!\nVIP status 30 kunga faollashtirildi! 👑", show_alert=True)

        # 8. REFRESH UI (Kabinetga qaytish)
        updated_data = {
            "user_id": db_user.user_id,
            "username": db_user.username,
            "status": db_user.status,
            "points": db_user.points,
            "referral_count": db_user.referral_count,
            "is_vip": True,
            "vip_expire_date": db_user.vip_expire_date.timestamp()
        }
        
        from handlers.user import personal_cabinet
        await personal_cabinet(callback, updated_data, state_fsm)

    except Exception as e:
        await session.rollback()
        raise e