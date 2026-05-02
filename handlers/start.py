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

# --- GLOBAL CONSTANTS & LOCKS ---
CH_NS, CH_ID = "custom", "active_channels"
_channel_fetch_lock = asyncio.Lock()

# ================================
# UTILS
# ================================

def normalize_channel_id(ch_id: int) -> int:
    """Telegram channel ID ni -100 formatga o'tkazadi"""
    ch_id = int(ch_id)
    if str(ch_id).startswith("-100"):
        return ch_id
    return int(f"-100{abs(ch_id)}")


# ================================
# CHANNEL FETCH
# ================================

async def _get_active_channels(session: AsyncSession) -> list:
    """
    Aktiv kanallarni cache yoki DB dan olish (FULL SAFE)
    """

    # ❗ session None protection
    if session is None:
        logger.warning("Session is None → returning empty channels")
        return []

    # 1. CACHE
    try:
        channels = await valkey.get(CH_NS, CH_ID)
        if channels is not None:
            return channels
    except Exception as e:
        logger.warning(f"Cache read error: {e}")

    # 2. LOCK (anti-stampede)
    async with _channel_fetch_lock:

        # double check
        try:
            channels = await valkey.get(CH_NS, CH_ID)
            if channels is not None:
                return channels
        except Exception:
            pass

        # 3. DB
        try:
            stmt = select(Channel).where(Channel.is_active == True)
            result = await session.execute(stmt)
            db_channels = result.scalars().all()

            channels_data = []
            for ch in db_channels:
                try:
                    ch_id = normalize_channel_id(ch.channel_id)

                    channels_data.append({
                        "id": ch_id,
                        "url": ch.url,
                        "title": ch.title
                    })
                except Exception as e:
                    logger.error(f"Channel parse error: {e}")

            # 4. CACHE WRITE
            try:
                await valkey.set(CH_NS, CH_ID, channels_data, ttl=900)
            except Exception as e:
                logger.warning(f"Cache write error: {e}")

            return channels_data

        except Exception as e:
            logger.critical(f"DB error in _get_active_channels: {e}")
            return []


# ================================
# SUB CHECK
# ================================

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession) -> tuple[bool, list]:
    """
    Majburiy obunani tekshiradi (FULL SAFE VERSION)
    """

    channels = await _get_active_channels(session)

    if not channels:
        return True, []

    semaphore = asyncio.Semaphore(5)

    async def _strict_check(ch):
        async with semaphore:
            try:
                member = await bot.get_chat_member(
                    chat_id=ch['id'],
                    user_id=user_id
                )

                if member.status in ["member", "administrator", "creator"]:
                    return None

                return ch

            except Exception as e:
                logger.warning(f"Sub check error {ch['id']}: {e}")
                return ch

    results = await asyncio.gather(*[_strict_check(ch) for ch in channels])

    not_joined = [r for r in results if r is not None]

    return len(not_joined) == 0, not_joined


# ================================
# KEYBOARD
# ================================

async def get_sub_keyboard(missing_channels: list) -> types.InlineKeyboardMarkup:
    buttons = []

    for ch in missing_channels:
        buttons.append([
            types.InlineKeyboardButton(
                text=f"📌 {ch['title']}",
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


# ================================
# START HANDLER
# ================================

@router.message(CommandStart())
async def cmd_start(
    message: types.Message,
    user: any,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext
):
    await state.clear()

    args = message.text.split()

    # --- SAFE SESSION CHECK ---
    if session is None:
        return await message.answer("⚠️ Server vaqtincha ishlamayapti, keyinroq urinib ko‘ring.")

    now_utc = datetime.now(timezone.utc)
    user_joined = getattr(user, 'joined_at', None)

    if user_joined:
        user_joined = user_joined.replace(tzinfo=timezone.utc) if user_joined.tzinfo is None else user_joined
        is_new_user = (now_utc - user_joined).total_seconds() < 60
    else:
        is_new_user = True

    # ========================
    # REFERRAL
    # ========================
    if len(args) > 1 and getattr(user, 'referred_by', None) is None and is_new_user:
        try:
            referrer_id = int(args[1])

            if referrer_id != message.from_user.id:
                stmt = select(DBUser).where(DBUser.user_id == message.from_user.id)
                res = await session.execute(stmt)
                db_user = res.scalar_one_or_none()

                if db_user and db_user.referred_by is None:
                    db_user.referred_by = referrer_id
                    await session.commit()

        except Exception as e:
            logger.warning(f"Referral error: {e}")

    # ========================
    # PRIVILEGE
    # ========================
    status = getattr(user, 'status', 'user')
    is_vip = getattr(user, 'is_vip', False)

    if status in ["creator", "admin"] or is_vip or message.from_user.id == config.CREATOR_ID:
        return await message.answer(
            f"👑 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
            reply_markup=get_main_menu(
                user_id=message.from_user.id,
                is_vip=is_vip,
                status=status
            ),
            parse_mode="HTML"
        )

    # ========================
    # SUB CHECK
    # ========================
    is_subbed, missing = await check_subscription(
        bot,
        message.from_user.id,
        session
    )

    if not is_subbed:
        kb = await get_sub_keyboard(missing)

        return await message.answer(
            "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )

    # ========================
    # SUCCESS
    # ========================
    await message.answer(
        f"👋 Xush kelibsiz, <b>{message.from_user.full_name}</b>!\n<b>AniNowuz</b> botiga xush kelibsiz.",
        reply_markup=get_main_menu(
            user_id=message.from_user.id,
            is_vip=is_vip,
            status=status
        ),
        parse_mode="HTML"
    )


# ================================
# REDIRECT
# ================================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def track_channel_redirect(callback: types.CallbackQuery, session: AsyncSession):
    try:
        if session is None:
            return await callback.answer("⚠️ Server xatosi", show_alert=True)

        ch_id = int(callback.data.split(":")[1])

        result = await session.execute(
            select(Channel).where(Channel.channel_id == ch_id)
        )
        channel = result.scalar_one_or_none()

        if not channel:
            return await callback.answer("❌ Kanal topilmadi!", show_alert=True)

        await session.execute(
            update(DBUser)
            .where(DBUser.user_id == callback.from_user.id)
            .values(last_redirected_channel=str(ch_id))
        )
        await session.commit()

        text = (
            f"📢 <b>Kanalga obuna bo‘ling</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Kanal: <b>{channel.title}</b>\n\n"
            f"1️⃣ Kanalga o‘ting\n"
            f"2️⃣ Obuna bo‘ling\n"
            f"3️⃣ Tasdiqlashni bosing"
        )

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 O‘tish", url=channel.url)],
            [types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"check_sub:{ch_id}")]
        ])

        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error(f"Redirect error: {e}")
        await callback.answer("⚠️ Xatolik", show_alert=True)


# ================================
# CHECK CALLBACK
# ================================

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub_callback(callback: types.CallbackQuery, user: any, session: AsyncSession, bot: Bot):

    if session is None:
        return await callback.answer("⚠️ Server xatosi", show_alert=True)

    is_subbed, missing = await check_subscription(
        bot,
        callback.from_user.id,
        session
    )

    if is_subbed:
        stmt = select(DBUser).where(DBUser.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        db_user = res.scalar_one_or_none()

        if db_user and db_user.referred_by and db_user.referred_by_channel != "done":
            ref_stmt = select(DBUser).where(DBUser.user_id == db_user.referred_by)
            ref_res = await session.execute(ref_stmt)
            referrer = ref_res.scalar_one_or_none()

            if referrer:
                referrer.points += 10
                referrer.referral_count += 1
                db_user.referred_by_channel = "done"

                await session.commit()
                await valkey.delete("db_users", referrer.user_id)

        await callback.message.delete()

        status = getattr(user, 'status', 'user')
        is_vip = getattr(user, 'is_vip', False)

        await callback.message.answer(
            "✅ Barcha obunalar tasdiqlandi!",
            reply_markup=get_main_menu(
                user_id=callback.from_user.id,
                is_vip=is_vip,
                status=status
            ),
            parse_mode="HTML"
        )

    else:
        await callback.answer("❌ Hali obuna bo‘lmadingiz", show_alert=True)

        try:
            new_kb = await get_sub_keyboard(missing)
            await callback.message.edit_reply_markup(reply_markup=new_kb)
        except:
            pass