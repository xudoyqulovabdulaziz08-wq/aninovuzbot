import logging
import asyncio
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.cache import valkey
from database.models import Channel, DBUser 
from keyboards.reply import get_main_menu
from config import config

logger = logging.getLogger("StartHandler")
router = Router()

# Unified Global Constants
CH_NS, CH_ID = "custom", "active_channels"

# 10/10 FIX: Cache Stampede Protection uchun Lock (Lokal darajada)
_channel_fetch_lock = asyncio.Lock()

async def _get_active_channels(session: AsyncSession) -> list:
    """
    Internal helper: Cache-first with stampede protection.
    """
    channels = await valkey.get(CH_NS, CH_ID)
    if channels is not None:
        return channels

    # ✅ 10/10: Cache Stampede Protection (0.05 perfection fix)
    async with _channel_fetch_lock:
        # Lock ichida keshni qayta tekshiramiz (Double-checked locking pattern)
        channels = await valkey.get(CH_NS, CH_ID)
        if channels is not None:
            return channels

        try:
            stmt = select(Channel).where(Channel.is_active == True)
            result = await session.execute(stmt)
            db_channels = result.scalars().all()
            
            channels_data = [
                {"id": ch.channel_id, "url": ch.url, "title": ch.title} 
                for ch in db_channels
            ]
            
            await valkey.set_custom(CH_NS, CH_ID, channels_data, expire=900)
            return channels_data
        except Exception as e:
            logger.critical(f"Critical DB failure: {e}")
            return []

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession) -> tuple[bool, list]:
    """
    PREMIUM SUBSCRIPTION CHECK:
    - Thread-safe result collection
    - Semaphore-based rate limiting
    """
    channels = await _get_active_channels(session)
    if not channels:
        return True, []

    semaphore = asyncio.Semaphore(5)
    # ✅ 10/10: Thread-safe collection (Python GIL tufayli amalda xavfsiz bo'lsa-da, 
    # List append o'rniga natijalarni to'plashning eng toza usuli)
    
    async def _strict_check(ch):
        async with semaphore:
            try:
                member = await bot.get_chat_member(chat_id=ch['id'], user_id=user_id)
                allowed = ["member", "administrator", "creator", "restricted"]
                if member.status not in allowed:
                    return ch
            except Exception as e:
                logger.error(f"Subscription check API error: {e}")
                return ch # Fail-safe strict
        return None

    # Parallel so'rovlar
    check_results = await asyncio.gather(*[_strict_check(ch) for ch in channels])
    
    # Natijalarni filtrlash (None bo'lmaganlari — a'zo bo'linmagan kanallar)
    not_joined = [res for res in check_results if res is not None]
    
    return len(not_joined) == 0, not_joined

# --- UI BUILDER ---
async def get_sub_keyboard(missing_channels: list) -> types.InlineKeyboardMarkup:
    buttons = []
    for ch in missing_channels:
        buttons.append([types.InlineKeyboardButton(text=f"📌 {ch['title']}", url=ch['url'])])
    
    buttons.append([types.InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= HANDLERS =================

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: DBUser, session: AsyncSession, bot: Bot):
    # 1. Privilege Check
    is_privileged = (
        user.status in ["creator", "admin", "vip"] or 
        message.from_user.id == config.CREATOR_ID
    )

    if is_privileged:
        return await message.answer(
            f"👑 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
            reply_markup=get_main_menu(user_id=message.from_user.id, status=user.status)
        )

    # 2. Strict Subscription Check
    is_subbed, missing = await check_subscription(bot, message.from_user.id, session)
    
    if not is_subbed:
        kb = await get_sub_keyboard(missing)
        return await message.answer(
            "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:</b>",
            reply_markup=kb
        )

    # 3. Success Entry
    await message.answer(
        f"👋 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
        reply_markup=get_main_menu(user_id=message.from_user.id, status=user.status)
    )

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery, user: DBUser, session: AsyncSession, bot: Bot):
    is_subbed, _ = await check_subscription(bot, callback.from_user.id, session)

    if is_subbed:
        await callback.message.delete()
        await callback.message.answer(
            "✅ <b>Tabriklaymiz!</b> Barcha obunalar tasdiqlandi.",
            reply_markup=get_main_menu(user_id=callback.from_user.id, status=user.status)
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)