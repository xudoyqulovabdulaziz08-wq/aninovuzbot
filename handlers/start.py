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
async def cmd_start(
    message: types.Message,
    user: any,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext
):
    await state.clear()

    try:
        args = message.text.split()
        user_id = message.from_user.id
        full_name = message.from_user.full_name
        now = datetime.now(timezone.utc)

        # =========================
        # SAFE SESSION GUARD
        # =========================
        if session is None:
            return await message.answer(
                "⚠️ Tizim vaqtincha ishlamayapti, keyinroq urinib ko‘ring.",
                parse_mode="HTML"
            )

        # =========================
        # USER JOIN TIME
        # =========================
        user_joined = getattr(user, "joined_at", None)
        is_new_user = True

        if user_joined:
            if user_joined.tzinfo is None:
                user_joined = user_joined.replace(tzinfo=timezone.utc)

            is_new_user = (now - user_joined).total_seconds() < 60

        # =========================
        # REFERRAL (SAFE + IDEMPOTENT)
        # =========================
        if len(args) > 1 and is_new_user:
            try:
                ref_id = int(args[1])

                if ref_id != user_id:
                    db_user = await session.scalar(
                        select(DBUser).where(DBUser.user_id == user_id)
                    )

                    if db_user and not db_user.referred_by:
                        db_user.referred_by = ref_id
                        await session.commit()

            except Exception as e:
                logger.warning(f"Referral parse error: {e}")

        # =========================
        # PRIVILEGE CHECK
        # =========================
        status = getattr(user, "status", "user")
        is_vip = getattr(user, "is_vip", False)
        is_admin_or_creator = status in ["creator", "admin"] or user_id == config.CREATOR_ID

        if is_vip:
            # agar model property bo‘lsa (recommended)
            try:
                is_vip = user.is_vip
            except:
                pass

        if is_admin_or_creator or is_vip:
            return await message.answer(
                f"👑 <b>Xush kelibsiz, {full_name}!</b>\n\n"
                f"🎯 Role: <b>{status.upper()}</b>\n"
                f"🚀 Sizga to‘liq access berildi.",
                reply_markup=get_main_menu(user_id, is_vip, status),
                parse_mode="HTML"
            )

        # =========================
        # SUB CHECK
        # =========================
        ok, missing = await check_subscription(bot, user_id, session)

        if not ok:
            text = (
                f"👋 <b>Assalomu alaykum, {full_name}!</b>\n\n"
                "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘lishingiz kerak.\n"
                "Bu bizga loyihani rivojlantirishga yordam beradi ❤️"
            )

            kb = await get_sub_keyboard(missing)

            return await message.answer(
                text,
                reply_markup=kb,
                parse_mode="HTML"
            )

        # =========================
        # SUCCESS UX
        # =========================
        await message.answer(
            f"🎉 <b>Xush kelibsiz, {full_name}!</b>\n\n"
            "✔ Ro‘yxatdan muvaffaqiyatli o‘tdingiz\n"
            "🚀 Endi botdan foydalanishingiz mumkin",
            reply_markup=get_main_menu(user_id, is_vip, status),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"cmd_start error: {e}", exc_info=True)

        await message.answer(
            "❌ <b>Ichki xatolik yuz berdi.</b>\n"
            "Iltimos, keyinroq qayta urinib ko‘ring.",
            parse_mode="HTML"
        )


# ================================
# CALLBACK
# ================================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def redirect(callback: types.CallbackQuery, session: AsyncSession):
    try:
        # UX: instant response (silent)
        await callback.answer()

        ch_id = int(callback.data.split(":")[1])

        # =========================
        # DB FETCH (SAFE)
        # =========================
        channel = await session.scalar(
            select(Channel).where(Channel.channel_id == ch_id)
        )

        if not channel:
            return await callback.answer(
                "❌ Kanal topilmadi yoki o‘chirilgan.",
                show_alert=True
            )

        # =========================
        # URL VALIDATION (IMPORTANT)
        # =========================
        if not channel.url:
            return await callback.answer(
                "⚠️ Bu kanal uchun link mavjud emas.",
                show_alert=True
            )

        # =========================
        # TRACKING (non-critical)
        # =========================
        try:
            await session.execute(
                update(DBUser)
                .where(DBUser.user_id == callback.from_user.id)
                .values(last_redirected_channel=str(ch_id))
            )
            await session.commit()
        except Exception as e:
            logger.warning(f"Tracking failed: {e}")

        # =========================
        # UX TEXT (clean + readable)
        # =========================
        text = (
            f"📢 <b>{channel.title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            "Botdan foydalanish uchun ushbu kanalga obuna bo‘ling.\n\n"
            "📌 <b>Qadamlar:</b>\n"
            "1️⃣ Kanalga o‘ting\n"
            "2️⃣ Obuna bo‘ling\n"
            "3️⃣ Botga qaytib tasdiqlang\n"
        )

        # =========================
        # INLINE KEYBOARD
        # =========================
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📢 Kanalga o'tish",
                    url=channel.url
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"check_sub:{ch_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⬅️ Orqaga",
                    callback_data="check_sub:all"
                )
            ]
        ])

        # =========================
        # SAFE EDIT (fallback included)
        # =========================
        try:
            await callback.message.edit_text(
                text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except:
            await callback.message.answer(
                text,
                reply_markup=kb,
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"redirect error: {e}")

        try:
            await callback.answer(
                "⚠️ Kanalga yo‘naltirishda muammo yuz berdi.",
                show_alert=True
            )
        except:
            pass


# ================================
# CHECK CALLBACK
# ================================

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub(callback: types.CallbackQuery, user: any, session: AsyncSession, bot: Bot):
    try:
        # UX: instant feedback
        await callback.answer("⏳ Tekshirilmoqda...")

        is_subbed, missing = await check_subscription(
            bot,
            callback.from_user.id,
            session
        )

        if not is_subbed:
            kb = await get_sub_keyboard(missing)

            await callback.answer(
                f"❌ Siz hali {len(missing)} ta kanalga obuna bo‘lmagansiz!",
                show_alert=True
            )

            try:
                await callback.message.edit_reply_markup(reply_markup=kb)
            except:
                pass

            return

        # =========================
        # REFERRAL SYSTEM (SAFE)
        # =========================
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

                # async notify (non-blocking UX)
                asyncio.create_task(
                    bot.send_message(
                        referrer.user_id,
                        "🎊 <b>Yangi referral!</b>\n+10 ball qo‘shildi 🔥",
                        parse_mode="HTML"
                    )
                )

        # =========================
        # CLEAN UX RESPONSE
        # =========================

        try:
            await callback.message.delete()
        except:
            pass

        status = getattr(user, "status", "user")
        is_vip = getattr(user, "is_vip", False)

        await callback.message.answer(
            (
                f"🎉 <b>Xush kelibsiz, {callback.from_user.first_name}!</b>\n\n"
                "✔ Barcha obunalar tasdiqlandi\n"
                "🚀 Endi botdan to‘liq foydalanishingiz mumkin"
            ),
            reply_markup=get_main_menu(
                user_id=callback.from_user.id,
                is_vip=is_vip,
                status=status
            ),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"check_sub error: {e}")

        await callback.answer(
            "⚠️ Serverda vaqtinchalik xatolik. Keyinroq urinib ko‘ring.",
            show_alert=True
        )