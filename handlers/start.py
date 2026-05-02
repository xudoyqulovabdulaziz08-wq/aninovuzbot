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

# Cache Constants
CH_NS, CH_ID = "custom", "active_channels"
_channel_fetch_lock = asyncio.Lock()

async def _get_active_channels(session: AsyncSession) -> list:
    """Aktiv kanallarni keshdan yoki bazadan olish."""
    channels = await valkey.get(CH_NS, CH_ID)
    if channels is not None:
        return channels

    async with _channel_fetch_lock:
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
            logger.critical(f"DB failure in start: {e}")
            return []

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession) -> tuple[bool, list]:
    """Obunani tekshirish."""
    channels = await _get_active_channels(session)
    if not channels:
        return True, []

    semaphore = asyncio.Semaphore(5)
    
    async def _strict_check(ch):
        async with semaphore:
            try:
                member = await bot.get_chat_member(chat_id=ch['id'], user_id=user_id)
                if member.status in ["member", "administrator", "creator"]:
                    return None
                return ch
            except Exception:
                return ch 
    
    results = await asyncio.gather(*[_strict_check(ch) for ch in channels])
    not_joined = [res for res in results if res is not None]
    return len(not_joined) == 0, not_joined

async def get_sub_keyboard(missing_channels: list) -> types.InlineKeyboardMarkup:
    """Obuna uchun tugmalarni yasash."""
    buttons = []
    for ch in missing_channels:
        # Har bir kanal uchun alohida redirect tugmasi
        buttons.append([types.InlineKeyboardButton(text=f"📌 {ch['title']}", callback_data=f"go_to_channel:{ch['id']}")])
    
    # Umumiy tekshirish tugmasi (startdan kelganda)
    buttons.append([types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_sub:all")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= HANDLERS =================

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: DBUser, session: AsyncSession, bot: Bot, state: FSMContext):
    await state.clear()
    args = message.text.split()
    
    # Yangi user ekanligini tekshirish
    now_utc = datetime.now(timezone.utc)
    user_joined = user.joined_at.replace(tzinfo=timezone.utc) if user.joined_at.tzinfo is None else user.joined_at
    is_new_user = (now_utc - user_joined).total_seconds() < 60

    if len(args) > 1 and user.referred_by is None and is_new_user:
        try:
            referrer_id = int(args[1])
            if referrer_id != user.user_id:
                user.referred_by = referrer_id
                await session.commit()
        except (ValueError, IndexError):
            pass

    # Imtiyozli foydalanuvchilar
    if user.status in ["creator", "admin"] or user.is_vip or user.user_id == config.CREATOR_ID:
        return await message.answer(
            f"👑 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
            reply_markup=get_main_menu(user_id=user.user_id, is_vip=user.is_vip, status=user.status),
            parse_mode="HTML"
        )

    is_subbed, missing = await check_subscription(bot, user.user_id, session)
    if not is_subbed:
        return await message.answer(
            "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:</b>",
            reply_markup=await get_sub_keyboard(missing),
            parse_mode="HTML"
        )

    await message.answer(
        f"👋 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
        reply_markup=get_main_menu(user_id=user.user_id, is_vip=user.is_vip, status=user.status),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("go_to_channel:"))
async def track_channel_redirect(callback: types.CallbackQuery, session: AsyncSession):
    try:
        ch_id = int(callback.data.split(":")[1])
        result = await session.execute(select(Channel).where(Channel.channel_id == ch_id))
        channel = result.scalar_one_or_none()

        if not channel:
            return await callback.answer("❌ Kanal topilmadi!", show_alert=True)

        await session.execute(update(DBUser).where(DBUser.user_id == callback.from_user.id).values(last_redirected_channel=str(ch_id)))
        await session.commit()

        text = (
            f"📢 <b>Kanalga obuna bo‘ling</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Kanal: <b>{channel.title}</b>\n\n"
            f"1️⃣ Kanalga o‘ting va a'zo bo'ling\n2️⃣ So'ngra 'Tasdiqlash' tugmasini bosing"
        )
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 Kanalga o‘tish", url=channel.url)],
            [types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"check_sub:{ch_id}")]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Redirect error: {e}")
        await callback.answer("⚠️ Xatolik")

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub_callback(callback: types.CallbackQuery, user: DBUser, session: AsyncSession, bot: Bot):
    # Har qanday check_sub:... callbackini ushlaydi
    is_subbed, missing = await check_subscription(bot, callback.from_user.id, session)

    if is_subbed:
        # ✅ REFERRAL BALL (Faqat obuna to'liq bo'lsa)
        if user.referred_by and user.referred_by_channel != "done":
            ref_res = await session.execute(select(DBUser).where(DBUser.user_id == user.referred_by))
            referrer = ref_res.scalar_one_or_none()

            if referrer:
                referrer.points += 10
                referrer.referral_count += 1
                user.referred_by_channel = "done"
                await session.commit()
                await valkey.delete("db_users", referrer.user_id)
                try:
                    await bot.send_message(referrer.user_id, "🎊 <b>Yangi referral obuna bo'ldi!</b>\nSizga <b>10 ball</b> berildi! 🔥", parse_mode="HTML")
                except: pass

        try: await callback.message.delete()
        except: pass
            
        await callback.message.answer(
            "✅ <b>Tabriklaymiz!</b> Barcha obunalar tasdiqlandi.",
            reply_markup=get_main_menu(user_id=callback.from_user.id, is_vip=user.is_vip, status=user.status),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)
        # Agar yangi kanallar chiqsa, keyboardni yangilash
        await callback.message.edit_reply_markup(reply_markup=await get_sub_keyboard(missing))