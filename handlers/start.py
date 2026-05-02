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
        if str(ch_id).startswith("-100"):
            return ch_id
        return int(f"-100{abs(ch_id)}")
    except Exception as e:
        logger.error(f"Channel ID normalize error: {e}")
        return ch_id


# ================================
# CHANNEL FETCH (SAFE + FAST)
# ================================

async def _get_active_channels(session: AsyncSession) -> list:
    if session is None:
        logger.error("❌ DB session None")
        return []

    # CACHE
    try:
        cached = await valkey.get(CH_NS, CH_ID)
        if cached:
            return cached
    except Exception as e:
        logger.warning(f"Cache read error: {e}")

    # LOCK (anti-stampede)
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

            channels_data = []
            for ch in db_channels:
                try:
                    channels_data.append({
                        "id": normalize_channel_id(ch.channel_id),
                        "url": ch.url,
                        "title": ch.title
                    })
                except Exception as e:
                    logger.error(f"Channel parse error: {e}")

            try:
                await valkey.set(CH_NS, CH_ID, channels_data, ttl=900)
            except Exception as e:
                logger.warning(f"Cache write error: {e}")

            return channels_data

        except Exception as e:
            logger.critical(f"DB channel fetch error: {e}")
            return []


# ================================
# SUB CHECK (OPTIMIZED)
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

                if member.status in ["member", "administrator", "creator"]:
                    return None

                return ch

            except Exception as e:
                logger.warning(f"Telegram API error: {e}")
                return ch

    results = await asyncio.gather(*[check(ch) for ch in channels])
    missing = [r for r in results if r]

    return len(missing) == 0, missing


# ================================
# KEYBOARD
# ================================

async def get_sub_keyboard(missing):
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            *[
                [types.InlineKeyboardButton(
                    text=f"📌 {ch['title']}",
                    callback_data=f"go_to_channel:{ch['id']}"
                )] for ch in missing
            ],
            [types.InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data="check_sub:all"
            )]
        ]
    )


# ================================
# START
# ================================

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: any, session: AsyncSession, bot: Bot, state: FSMContext):
    await state.clear()

    if not session:
        return await message.answer("❌ Server error. Keyinroq urinib ko‘ring.")

    try:
        args = message.text.split()
        now = datetime.now(timezone.utc)

        user_joined = getattr(user, "joined_at", None)
        is_new_user = True

        if user_joined:
            if user_joined.tzinfo is None:
                user_joined = user_joined.replace(tzinfo=timezone.utc)
            is_new_user = (now - user_joined).total_seconds() < 60

        # ================= REF =================
        if len(args) > 1 and not getattr(user, "referred_by", None) and is_new_user:
            try:
                ref_id = int(args[1])
                if ref_id != message.from_user.id:

                    db_user = await session.scalar(
                        select(DBUser).where(DBUser.user_id == message.from_user.id)
                    )

                    if db_user and not db_user.referred_by:
                        db_user.referred_by = ref_id
                        await session.commit()

            except Exception as e:
                logger.warning(f"Referral error: {e}")

        # ================= PRIV =================
        status = getattr(user, "status", "user")
        is_vip = getattr(user, "is_vip", False)

        if status in ["creator", "admin"] or is_vip or message.from_user.id == config.CREATOR_ID:
            return await message.answer(
                f"👑 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
                reply_markup=get_main_menu(message.from_user.id, is_vip, status),
                parse_mode="HTML"
            )

        # ================= SUB CHECK =================
        ok, missing = await check_subscription(bot, message.from_user.id, session)

        if not ok:
            kb = await get_sub_keyboard(missing)
            return await message.answer(
                "📢 <b>Obuna bo‘lish shart!</b>",
                reply_markup=kb,
                parse_mode="HTML"
            )

        # ================= SUCCESS =================
        return await message.answer(
            f"👋 Xush kelibsiz, <b>{message.from_user.full_name}</b>",
            reply_markup=get_main_menu(message.from_user.id, is_vip, status),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Start handler crash: {e}")
        return await message.answer("❌ Xatolik yuz berdi")


# ================================
# CALLBACK
# ================================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def redirect(callback: types.CallbackQuery, session: AsyncSession):
    try:
        ch_id = int(callback.data.split(":")[1])

        channel = await session.scalar(
            select(Channel).where(Channel.channel_id == ch_id)
        )

        if not channel:
            return await callback.answer("❌ Kanal topilmadi", show_alert=True)

        await session.execute(
            update(DBUser)
            .where(DBUser.user_id == callback.from_user.id)
            .values(last_redirected_channel=str(ch_id))
        )
        await session.commit()

        text = f"""
📢 <b>Kanalga obuna bo‘ling</b>

📌 {channel.title}

1️⃣ O‘ting
2️⃣ Obuna bo‘ling
3️⃣ Tasdiqlang
"""

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 Kanal", url=channel.url)],
            [types.InlineKeyboardButton(text="✅ Tekshirish", callback_data=f"check_sub:{ch_id}")]
        ])

        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()

    except Exception as e:
        logger.error(f"Redirect error: {e}")
        await callback.answer("❌ Xatolik")


# ================================
# CHECK CALLBACK
# ================================

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub(callback: types.CallbackQuery, user: any, session: AsyncSession, bot: Bot):

    try:
        ok, missing = await check_subscription(bot, callback.from_user.id, session)

        if ok:
            await callback.message.delete()

            status = getattr(user, "status", "user")
            is_vip = getattr(user, "is_vip", False)

            await callback.message.answer(
                "✅ Tasdiqlandi!",
                reply_markup=get_main_menu(callback.from_user.id, is_vip, status),
                parse_mode="HTML"
            )
        else:
            await callback.answer("❌ Obuna bo‘ling", show_alert=True)
            kb = await get_sub_keyboard(missing)
            await callback.message.edit_reply_markup(reply_markup=kb)

    except Exception as e:
        logger.error(f"Check sub error: {e}")
        await callback.answer("❌ Xatolik")