import logging
import asyncio
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone

from database.cache import valkey
from database.models import Channel, DBUser
from keyboards.reply import get_main_menu
from config import config

logger = logging.getLogger("StartHandler")
router = Router()

CH_NS, CH_ID = "custom", "active_channels"
_channel_lock = asyncio.Lock()

# =========================
# UTILS
# =========================

def normalize_channel_id(ch_id: int) -> int:
    try:
        ch_id = int(ch_id)
        return ch_id if str(ch_id).startswith("-100") else int(f"-100{abs(ch_id)}")
    except:
        return ch_id


# =========================
# FAST CHANNEL CACHE
# =========================

async def get_active_channels(session: AsyncSession):
    if not session:
        return []

    # 1. CACHE FAST PATH
    try:
        cached = await valkey.get(CH_NS, CH_ID)
        if cached:
            return cached
    except:
        pass

    # 2. LOCKED DB FETCH (anti-stampede)
    async with _channel_lock:
        try:
            cached = await valkey.get(CH_NS, CH_ID)
            if cached:
                return cached

            result = await session.execute(
                select(Channel.channel_id, Channel.url, Channel.title)
                .where(Channel.is_active.is_(True))
            )

            channels = [
                {
                    "id": normalize_channel_id(ch.channel_id),
                    "url": ch.url,
                    "title": ch.title
                }
                for ch in result.all()
            ]

            await valkey.set(CH_NS, CH_ID, channels, ttl=900)
            return channels

        except:
            return []


# =========================
# FAST SUB CHECK
# =========================

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession):
    channels = await get_active_channels(session)
    if not channels:
        return True, []

    async def check(ch):
        try:
            m = await bot.get_chat_member(ch["id"], user_id)
            return None if m.status in ("member", "administrator", "creator") else ch
        except:
            return ch

    results = await asyncio.gather(*[check(ch) for ch in channels])
    missing = [r for r in results if r]

    return len(missing) == 0, missing


# =========================
# KEYBOARD (FAST BUILD)
# =========================

def build_sub_keyboard(missing):
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


# =========================
# START (ULTRA OPTIMIZED)
# =========================

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: any, session: AsyncSession, bot: Bot, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id
    full_name = message.from_user.full_name
    now = datetime.now(timezone.utc)

    if not session:
        return await message.answer("⚠️ Server band")

    args = message.text.split()

    try:
        # =========================
        # USER CACHE AVOID EXTRA DB
        # =========================
        is_vip = getattr(user, "is_vip", False)
        status = getattr(user, "status", "user")

        # =========================
        # REFERRAL (ONLY IF NEW USER)
        # =========================
        if len(args) > 1:
            try:
                ref_id = int(args[1])
                if ref_id != user_id:
                    await session.execute(
                        update(DBUser)
                        .where(DBUser.user_id == user_id)
                        .values(referred_by=ref_id)
                    )
            except:
                pass

        # =========================
        # VIP FAST PATH
        # =========================
        if status in ("admin", "creator") or is_vip:
            return await message.answer(
                f"👑 <b>Welcome {full_name}</b>\n🚀 Full access",
                reply_markup=get_main_menu(user_id, is_vip, status),
                parse_mode="HTML"
            )

        # =========================
        # SUB CHECK
        # =========================
        ok, missing = await check_subscription(bot, user_id, session)

        if not ok:
            return await message.answer(
                f"👋 <b>{full_name}</b>\n\nObuna bo‘ling:",
                reply_markup=build_sub_keyboard(missing),
                parse_mode="HTML"
            )

        # =========================
        # SUCCESS
        # =========================
        await message.answer(
            f"🎉 <b>Xush kelibsiz {full_name}</b>",
            reply_markup=get_main_menu(user_id, is_vip, status),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"start error: {e}")
        await message.answer("❌ Xatolik yuz berdi")


# =========================
# CHANNEL REDIRECT (OPTIMIZED)
# =========================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def redirect(callback: types.CallbackQuery, session: AsyncSession):
    await callback.answer()

    ch_id = int(callback.data.split(":")[1])

    channel = await session.scalar(
        select(Channel).where(Channel.channel_id == ch_id)
    )

    if not channel or not channel.url:
        return await callback.answer("❌ Kanal topilmadi", show_alert=True)

    asyncio.create_task(
        session.execute(
            update(DBUser)
            .where(DBUser.user_id == callback.from_user.id)
            .values(last_redirected_channel=str(ch_id))
        )
    )

    await callback.message.edit_text(
        f"📢 <b>{channel.title}</b>\nObuna bo‘ling",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 Join", url=channel.url)],
            [types.InlineKeyboardButton(text="✅ Check", callback_data=f"check_sub:{ch_id}")]
        ]),
        parse_mode="HTML"
    )


# =========================
# CHECK SUB (FAST PATH)
# =========================

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub(callback: types.CallbackQuery, user: any, session: AsyncSession, bot: Bot):
    await callback.answer("⏳")

    ok, missing = await check_subscription(bot, callback.from_user.id, session)

    if not ok:
        return await callback.answer(f"❌ {len(missing)} kanal yetishmaydi", show_alert=True)

    db_user = await session.scalar(
        select(DBUser).where(DBUser.user_id == callback.from_user.id)
    )

    if db_user and db_user.referred_by:
        ref = await session.scalar(
            select(DBUser).where(DBUser.user_id == db_user.referred_by)
        )

        if ref:
            ref.points += 10
            db_user.referred_by = None

            asyncio.create_task(valkey.delete("db_users", ref.user_id))

    await session.commit()

    try:
        await callback.message.delete()
    except:
        pass

    await callback.message.answer(
        f"🎉 <b>Tayyor!</b>",
        reply_markup=get_main_menu(callback.from_user.id, getattr(user, "is_vip", False), getattr(user, "status", "user")),
        parse_mode="HTML"
    )