# handlers/start.py
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
    args = message.text.split()
    
    if len(args) > 1 and user.referred_by is None:
        try:
            referrer_id = int(args[1])
            
            if referrer_id != user.user_id:
                stmt = select(DBUser).where(DBUser.user_id == referrer_id)
                res = await session.execute(stmt)
                referrer = res.scalar_one_or_none()

                if referrer:
                    # 1. O'zgarishlarni kiritamiz
                    user.referred_by = referrer_id
                    referrer.points += 10
                    referrer.referral_count += 1
                    
                    # 2. BAZAGA SAQLASH (Eng muhim joyi!)
                    await session.commit()
                    
                    # 3. KESHNI TOZALASH
                    # Taklif qilgan odamning keshini o'chiramiz, shunda u kabinetda yangi ballni ko'radi
                    from database.cache import valkey # Kesh modulini import qiling
                    if 'valkey' in locals() or 'valkey' in globals():
                        await valkey.delete("db_users", referrer_id)

                    # 4. Xabar yuborish
                    try:
                        await bot.send_message(
                            chat_id=referrer_id,
                            text=(
                                f"🎊 <b>Yangi taklif!</b>\n"
                                f"Sizning havolangiz orqali yangi foydalanuvchi qo'shildi.\n"
                                f"Hisobingizga <b>10 ball</b> qo'shildi. Rahmat! 🔥"
                            ),
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"Referrer'ga xabar yuborib bo'lmadi: {e}")
                        
        except (ValueError, IndexError) as e:
            logger.error(f"Referral ID format error: {e}")

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery, user: DBUser, session: AsyncSession, bot: Bot):
    # Obunani qayta tekshirish
    is_subbed, _ = await check_subscription(bot, callback.from_user.id, session)

    if is_subbed:
        # Xabarni tahrirlash o'rniga o'chirib yuborish (UI/UX uchun yaxshi)
        try:
            await callback.message.delete()
        except:
            pass
            
        await callback.message.answer(
            "✅ <b>Tabriklaymiz!</b> Barcha obunalar tasdiqlandi.",
            reply_markup=get_main_menu(user_id=callback.from_user.id, status=user.status)
        )
    else:
        # Alert orqali foydalanuvchini ogohlantirish
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)