import logging
import asyncio
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from aiogram.fsm.context import FSMContext

from database.cache import valkey
from database.models import Channel, DBUser 
from keyboards.reply import get_main_menu
from config import config

logger = logging.getLogger("StartHandler")
router = Router()

CH_NS, CH_ID = "custom", "active_channels"
_channel_fetch_lock = asyncio.Lock()


# ================================
# UTILS
# ================================

def normalize_channel_id(ch_id: int) -> int:
    try:
        ch_id = int(ch_id)
        return ch_id if str(ch_id).startswith("-100") else int(f"-100{abs(ch_id)}")
    except Exception:
        logger.error(f"[normalize_channel_id] Invalid channel id: {ch_id}")
        return ch_id


# ================================
# CHANNEL CACHE + DB
# ================================

async def _get_active_channels(session: AsyncSession) -> list:
    if session is None:
        logger.error("[CHANNEL_FETCH] Session is None")
        return []

    # --- CACHE READ ---
    try:
        cached = await valkey.get(CH_NS, CH_ID)
        if cached:
            return cached
    except Exception as e:
        logger.warning(f"[CACHE_READ_ERROR] {e}")

    async with _channel_fetch_lock:
        try:
            cached = await valkey.get(CH_NS, CH_ID)
            if cached:
                return cached
        except Exception:
            pass

        try:
            stmt = select(Channel).where(Channel.is_active == True)
            result = await session.execute(stmt)
            db_channels = result.scalars().all()

            if not db_channels:
                logger.warning("[CHANNELS] No active channels found")

            channels_data = []

            for ch in db_channels:
                try:
                    channels_data.append({
                        "id": normalize_channel_id(ch.channel_id),
                        "url": ch.url,
                        "title": ch.title
                    })
                except Exception as e:
                    logger.error(f"[CHANNEL_PARSE_ERROR] {e}")

            try:
                await valkey.set(CH_NS, CH_ID, channels_data, ttl=900)
            except Exception as e:
                logger.warning(f"[CACHE_WRITE_ERROR] {e}")

            return channels_data

        except Exception as e:
            logger.critical(f"[DB_CHANNEL_ERROR] {e}")
            return []


# ================================
# SUB CHECK (FAST + SAFE)
# ================================

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession):
    channels = await _get_active_channels(session)

    if not channels:
        return True, []

    semaphore = asyncio.Semaphore(5)

    async def check(ch):
        async with semaphore:
            try:
                member = await bot.get_chat_member(ch["id"], user_id)

                if member.status in ("member", "administrator", "creator"):
                    return None

                return ch

            except Exception as e:
                logger.warning(f"[SUB_CHECK_FAIL] channel={ch.get('id')} error={e}")
                return ch

    results = await asyncio.gather(*[check(ch) for ch in channels], return_exceptions=True)

    missing = [r for r in results if isinstance(r, dict)]

    return len(missing) == 0, missing


# ================================
# KEYBOARD
# ================================

async def get_sub_keyboard(missing_channels: list):
    try:
        buttons = []

        for ch in missing_channels:
            buttons.append([
                types.InlineKeyboardButton(
                    text=f"📌 {ch.get('title','Channel')}",
                    callback_data=f"go_to_channel:{ch['id']}"
                )
            ])

        buttons.append([
            types.InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data="check_sub:all"
            )
        ])

        return types.InlineKeyboardMarkup(inline_keyboard=buttons)

    except Exception as e:
        logger.error(f"[KEYBOARD_ERROR] {e}")
        return types.InlineKeyboardMarkup(inline_keyboard=[])


# ================================
# START HANDLER
# ================================

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: any, session: AsyncSession, bot: Bot, state: FSMContext):

    await state.clear()

    if session is None:
        logger.critical("[START] Session missing")
        return await message.answer("⚠️ Server xatosi, keyinroq urinib ko‘ring.")

    try:
        args = message.text.split()
    except Exception:
        args = []

    now_utc = datetime.now(timezone.utc)

    user_joined = getattr(user, "joined_at", None)

    if user_joined:
        try:
            if user_joined.tzinfo is None:
                user_joined = user_joined.replace(tzinfo=timezone.utc)

            is_new_user = (now_utc - user_joined).total_seconds() < 60
        except Exception:
            is_new_user = True
    else:
        is_new_user = True


    # ========================
    # REFERRAL SAFE
    # ========================
    if len(args) > 1 and getattr(user, "referred_by", None) is None and is_new_user:
        try:
            referrer_id = int(args[1])

            if referrer_id != message.from_user.id:

                res = await session.execute(
                    select(DBUser).where(DBUser.user_id == message.from_user.id)
                )
                db_user = res.scalar_one_or_none()

                if db_user and db_user.referred_by is None:
                    db_user.referred_by = referrer_id
                    await session.commit()

        except Exception as e:
            logger.error(f"[REFERRAL_ERROR] {e}")


    # ========================
    # PRIVILEGE CHECK
    # ========================
    status = getattr(user, "status", "user")
    is_vip = getattr(user, "is_vip", False)

    if status in ("creator", "admin") or is_vip or message.from_user.id == config.CREATOR_ID:
        return await message.answer(
            f"👑 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
            reply_markup=get_main_menu(message.from_user.id, is_vip, status),
            parse_mode="HTML"
        )


    # ========================
    # SUB CHECK
    # ========================
    try:
        is_subbed, missing = await check_subscription(bot, message.from_user.id, session)
    except Exception as e:
        logger.critical(f"[SUB_CHECK_FATAL] {e}")
        return await message.answer("⚠️ Tekshirishda xatolik")

    if not is_subbed:
        kb = await get_sub_keyboard(missing)

        return await message.answer(
            "📢 <b>Obuna bo‘ling:</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )


    # ========================
    # SUCCESS
    # ========================
    return await message.answer(
        f"👋 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
        reply_markup=get_main_menu(message.from_user.id, is_vip, status),
        parse_mode="HTML"
    )