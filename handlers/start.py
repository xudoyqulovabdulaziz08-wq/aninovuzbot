import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Union, Tuple

# Aiogram importlari
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton
)

# SQLAlchemy importlari
from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

# Ichki modullar (Proyektingiz tuzilmasiga qarab)
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

async def get_active_channels(session: AsyncSession) -> list:
    if session is None:
        logger.warning("⚠️ Session yo'q, keshni tekshiraman.") #

    # 1. Keshdan tezkor olish
    try:
        cached = await valkey.get(CH_NS, CH_ID)
        if cached: return cached
    except Exception as e:
        logger.error(f"Cache error: {e}")

    # 2. Baza bilan ishlash (SafeSession orqali)
    async with _channel_lock:
        try:
            # Ikkinchi marta keshni tekshirish (anti-stampede)
            cached = await valkey.get(CH_NS, CH_ID)
            if cached: return cached

            if session:
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
                # 15 daqiqaga keshga yozish
                await valkey.set(CH_NS, CH_ID, channels, ttl=900)
                return channels
        except Exception as e:
            logger.error(f"DB Fetch error: {e}")
            return []


# =========================
# FAST SUB CHECK
# =========================


# =========================
# KEYBOARD (FAST BUILD)
# =========================
# DIQQAT: Bu oddiy def, await bilan chaqirilmaydi!
def build_sub_keyboard(missing: list):
    builder = InlineKeyboardBuilder()
    
    # Har bir kanal uchun alohida qator (UX: bosishga qulay)
    for ch in missing:
        builder.row(types.InlineKeyboardButton(
            text=f"📢 {ch['title']}", 
            # go_to_channel handleri orqali o'tish
            callback_data=f"go_to_channel:{ch['id']}")
        )
    
    # Tekshirish tugmasi har doim oxirida va ajralib turadi
    builder.row(types.InlineKeyboardButton(
        text="🔄 Obunani tekshirish", 
        callback_data="check_sub:all")
    )
    return builder.as_markup()

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession):
    # Kanallarni keshdan yoki bazadan olish
    channels = await get_active_channels(session)
    if not channels:
        return True, []

    # API so'rovlarni parallel yuborish (Tezkorlik: High-Load uchun)
    async def check(ch):
        try:
            m = await bot.get_chat_member(ch["id"], user_id)
            return None if m.status in ("member", "administrator", "creator") else ch
        except Exception:
            # Xatolik bo'lsa (masalan bot kanalda admin emas), foydalanuvchini kanalga yo'naltiramiz
            return ch 

    results = await asyncio.gather(*[check(ch) for ch in channels])
    missing = [r for r in results if r]
    return len(missing) == 0, missing
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
        # PRIVILEGE CHECK (OPTIMIZED UX)
        # =========================
        status = user.get("status", "user")
        is_vip = user.get("is_vip", False)
        is_admin = status in ["creator", "admin"] or user_id == config.CREATOR_ID

        if is_admin or is_vip:
            # Statusga qarab tegishli sarlavha va emojini tanlash
            if status == "creator":
                header, icon = "Tizim Yaratuvchisi", "⚡"
            elif status == "admin":
                header, icon = "Administrator", "🛠"
            else:
                header, icon = "VIP Foydalanuvchi", "💎"

            # Foydalanuvchi hisobidagi ochkolarni ham ko'rsatish (UX uchun foydali)
            points = user.get("points", 0)
            
            text = (
                f"{icon} <b>Xush kelibsiz, {full_name}!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Statusingiz:</b> <code>{header}</code>\n"
                f"💰 <b>Balansingiz:</b> <code>{points} ball</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🚀 Botning barcha funksiyalari siz uchun ochiq."
            )

            return await message.answer(
                text=text,
                reply_markup=get_main_menu(user_id, is_vip, status),
                parse_mode="HTML"
            )

        # =========================
        # SUB CHECK (HIGH-END UX)
        # =========================
        # start.py ichida
        ok, missing = await check_subscription(bot, user_id, session)

        if not ok:
           
            kb = build_sub_keyboard(missing) 
    
            text = (
                f"👋 <b>Assalomu alaykum, {message.from_user.full_name}!</b>\n\n"
                f"Botimizdan foydalanish uchun quyidagi kanallarga a'zo bo'lishingiz kerak.\n\n"
                f"<i>Obuna bo'lib, '🔄 Obunani tekshirish' tugmasini bosing.</i>"
            )
    
            return await message.answer(
                text=text,
                reply_markup=kb,
                parse_mode="HTML"

            )

        # =========================
        # SUCCESS (PREMIUM UX)
        # =========================
        # Keshdan olingan ballar va statusni ko'rsatish
        points = user.get("points", 0)
        
        text = (
            f"🎉 <b>Tabriklaymiz, {full_name}!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Siz muvaffaqiyatli ro‘yxatdan o‘tdingiz.</b>\n\n"
            f"💰 <b>Balansingiz:</b> <code>{points} ball</code>\n"
            f"🎁 <b>Siz uchun:</b> Barcha funksiyalar faollashtirildi!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f" <b>Boshlash uchun quyidagi menyudan foydalaning:</b>"
        )

        return await message.answer(
            text=text,
            reply_markup=get_main_menu(user_id, is_vip, status),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"start error: {e}", exc_info=True)
        
        # Xatolik matnini ham UX jihatdan chiroyli qilish
        error_text = (
            "❌ <b>Texnik uzilish!</b>\n\n"
            "Kutilmagan xatolik tufayli tizimda uzilish yuz berdi. "
            "Muhandislarimiz bu haqda xabar topishdi. 🛠\n\n"
            "🔄 <i>Iltimos, bir ozdan so‘ng /start buyrug‘ini qayta bosing.</i>"
        )
        
        await message.answer(
            text=error_text,
            parse_mode="HTML"
        )

# =========================
# CHANNEL REDIRECT (OPTIMIZED)
# =========================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def redirect_handler(callback: types.CallbackQuery, session: AsyncSession):
    """
    DbSessionMiddleware'ning SafeSession xususiyatiga moslashtirilgan handler.
    """
    await callback.answer()
    
    # 1. CIRCUIT BREAKER TEKSHIRUVI
    # Agar baza o'chgan bo'lsa, SafeSession ichidagi haqiqiy sessiya None bo'ladi.
    # Bu holatda session.scalar() chaqirish RuntimeError beradi.[cite: 12]
    if isinstance(session._session, type(None)):
        return await callback.answer(
            "⚠️ Ma'lumotlar bazasi vaqtincha mavjud emas.\n"
            "Iltimos, keyinroq qayta urinib ko'ring.",
            show_alert=True
        )

    try:
        # Callback'dan kanal ID sini ajratib olish
        ch_id_str = callback.data.split(":")[1]
        ch_id = int(ch_id_str)

        # 2. BAZADAN QIDIRISH (Sessiya borligi aniq)[cite: 12, 19]
        # Bu yerda SafeSession orqali haqiqiy session.execute ishga tushadi
        stmt = select(Channel).where(Channel.channel_id == ch_id)
        channel = await session.scalar(stmt)

        if not channel or not channel.url:
            return await callback.answer(
                "❌ Kanal topilmadi yoki o'chirilgan.", 
                show_alert=True
            )

        # 3. INTERFEYS (UX)
        text = (
            f"📢 <b>Kanal: {channel.title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Botdan foydalanishni davom ettirish uchun "
            f"ushbu kanalga a'zo bo'lishingiz shart.\n"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Kanalga o'tish", url=channel.url)],
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"check_sub:{ch_id}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="check_sub:all")]
        ])

        await callback.message.edit_text(
            text=text, 
            reply_markup=kb, 
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Redirect handler error: {e}", exc_info=True)
        await callback.answer(
            "❌ Xatolik yuz berdi. Qayta urinib ko'ring.", 
            show_alert=True
        )

# =========================
# CHECK SUB (FAST PATH)
# =========================

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub(callback: types.CallbackQuery, user: dict, session: AsyncSession, bot: Bot):
    # 1. Instant Feedback
    await callback.answer("⏳ Tekshirilmoqda...")

    user_id = callback.from_user.id
    
    # 2. Obunani tekshirish
    ok, missing = await check_subscription(bot, user_id, session)

    if not ok:
        count = len(missing)
        return await callback.answer(
            f"❌ Obuna to'liq emas!\nYana {count} ta kanalga a'zo bo'lishingiz kerak.", 
            show_alert=True
        )

    # 3. Referral mantiqi (Faqat session mavjud bo'lsa)
    if not isinstance(session._session, type(None)):
        try:
            # Foydalanuvchini bazadan olish
            db_user = await session.scalar(
                select(DBUser).where(DBUser.user_id == user_id)
            )

            # Agar foydalanuvchi taklif qilingan bo'lsa va hali ochko berilmagan bo'lsa
            if db_user and db_user.referred_by:
                ref_id = db_user.referred_by
                
                # Taklif qilgan odamni (referrer) topish
                referrer = await session.scalar(
                    select(DBUser).where(DBUser.user_id == ref_id)
                )

                if referrer:
                    referrer.points += 10
                    referrer.referral_count += 1
                    # Referral mantiqi takrorlanmasligi uchun referred_by ni tozalaymiz
                    db_user.referred_by = None 
                    
                    await session.commit()
                    
                    # Referrer keshini o'chirish (Middleware keyingi safar yangi ochkolarni keshlaydi)
                    await valkey.delete("db_users", ref_id)

                    # Referrerga bildirishnoma yuborish (Async Task)
                    asyncio.create_task(
                        bot.send_message(
                            ref_id, 
                            "🎊 <b>Tabriklaymiz!</b>\nSizning taklifingiz muvaffaqiyatli obuna bo'ldi: +10 ball! 🔥",
                            parse_mode="HTML"
                        )
                    )
        except Exception as e:
            logger.error(f"Referral reward error: {e}")

    # 4. Success UX
    status = user.get("status", "user")
    is_vip = user.get("is_vip", False)
    
    # Xabarni chiroyli tozalash
    try:
        await callback.message.delete()
    except:
        pass

    success_text = (
        f"✅ <b>Muvaffaqiyatli tasdiqlandi!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 <b>Xush kelibsiz, {callback.from_user.first_name}!</b>\n"
        f"Endi botdan cheklovlarsiz foydalanishingiz mumkin.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 <b>Asosiy menyu:</b>"
    )

    await callback.message.answer(
        text=success_text,
        reply_markup=get_main_menu(user_id, is_vip, status),
        parse_mode="HTML"
    )