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
from database.repository import UserRepository
from keyboards.reply import get_main_menu
from config import config

logger = logging.getLogger("StartHandler")
router = Router()

CH_NS, CH_ID = "custom", "active_channels"
_channel_lock = asyncio.Lock()

# =========================
# UTILS & CACHE
# =========================

def normalize_channel_id(ch_id: Union[int, str]) -> int:
    try:
        val = str(ch_id)
        return int(val) if val.startswith("-100") else int(f"-100{abs(int(val))}")
    except (ValueError, TypeError):
        return 0

async def get_active_channels(session: AsyncSession) -> List[Dict[str, Any]]:
    """Kanal ro'yxatini keshdan/bazadan xavfsiz olish"""
    try:
        cached = await valkey.get(CH_NS, CH_ID)
        if cached: return cached
    except Exception as e:
        logger.error(f"Cache Read Error: {e}")

    async with _channel_lock:
        # Anti-stampede check
        cached = await valkey.get(CH_NS, CH_ID)
        if cached: return cached

        # SafeSession check[cite: 12]
        if session is None or isinstance(session._session, type(None)):
            return []

        try:
            result = await session.execute(
                select(Channel.channel_id, Channel.url, Channel.title)
                .where(Channel.is_active.is_(True))
            )
            channels = [
                {"id": normalize_channel_id(ch.channel_id), "url": ch.url, "title": ch.title}
                for ch in result.all()
            ]
            await valkey.set(CH_NS, CH_ID, channels, ttl=900)
            return channels
        except Exception as e:
            logger.error(f"DB Fetch error: {e}")
            return []



# =========================
# KEYBOARD (FAST BUILD)
# =========================

def build_sub_keyboard(missing: list):
    """
    UX jihatdan optimallashtirilgan va bosishga qulay keyboard.
    """
    builder = InlineKeyboardBuilder()
    
    # Kanallar ro'yxati - har biri alohida qator va tartib raqami bilan
    for index, ch in enumerate(missing, 1):
        builder.row(types.InlineKeyboardButton(
            text=f"🔹 {index}-kanal: {ch['title']}", 
            callback_data=f"go_to_channel:{ch['id']}")
        )
    
    # Tasdiqlash tugmasi - asosiy fokus markazi
    builder.row(types.InlineKeyboardButton(
        text="✅ Obunani tasdiqlash", 
        callback_data="check_sub:all")
    )
    
    
    
    return builder.as_markup()





async def check_subscription(bot: Bot, user_id: int, session: AsyncSession):
    """
    High-Load va Rate-Limit himoyasiga ega tekshiruv.
    """
    # 1. Creator uchun VIP yo'lak (Bazada muammo bo'lsa ham ishlaydi)
    if user_id == config.CREATOR_ID:
        return True, []

    # 2. Kanallarni kesh/bazadan olish
    channels = await get_active_channels(session)
    if not channels:
        return True, []

    # 3. Parallel so'rovlar uchun limit (masalan, bir vaqtda max 5 ta API so'rov)
    sem = asyncio.Semaphore(5)

    async def check(ch):
        async with sem:
            try:
                # Cache-aside: kelajakda bu yerga individual a'zolik keshini qo'shish mumkin
                m = await bot.get_chat_member(ch["id"], user_id)
                if m.status in ("member", "administrator", "creator"):
                    return None
                return ch
            except Exception as e:
                # Bot kanalda admin bo'lmasa yoki kanal topilmasa, xavfsizlik uchun 'missing' deb qaytaradi
                logger.warning(f"Sub check failed for {ch['id']}: {e}")
                return ch 

    # Parallel bajarish orqali javob vaqtini minimal qilish
    results = await asyncio.gather(*[check(ch) for ch in channels])
    missing = [r for r in results if r]
    
    return len(missing) == 0, missing
# =========================
# START (ULTRA OPTIMIZED)
# =========================

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: dict, session: AsyncSession, bot: Bot, state: FSMContext):
    """
    Pro Max Start Handler: Xavfsiz, tezkor va yuqori darajadagi UX.
    """
    await state.clear()

    user_id = message.from_user.id
    full_name = message.from_user.full_name
    
    # Circuit Breaker: Agar middleware sessionni bog'lay olmagan bo'lsa
    if session is None or isinstance(session._session, type(None)):
        return await message.answer(
            "⚠️ <b>Tizimda texnik ishlar:</b>\n"
            "Hozirda ma'lumotlar bazasi band. Iltimos, 1 daqiqadan so'ng urinib ko'ring.",
            parse_mode="HTML"
        )

    args = message.text.split()

    try:
        # =========================
        # USER DATA (KESHDAN)
        # =========================
        status = user.get("status", "user")
        is_vip = user.get("is_vip", False)
        points = user.get("points", 0)
        # CREATOR_ID configdan tekshiriladi
        is_admin = status in ["creator", "admin"] or user_id == config.CREATOR_ID

        # =========================
        # REFERRAL (OUTBOX COMPATIBLE)
        # =========================
        # Faqat yangi foydalanuvchi bo'lsa va argument bo'lsa
        if len(args) > 1 and not user.get("is_registered", False):
            try:
                ref_id = int(args[1])
                if ref_id != user_id:
                    # Repository orqali yozish keshni Outbox orqali sinxronlaydi[cite: 12]
                    await UserRepository.set_referrer(session, user_id, ref_id)
            except (ValueError, Exception) as e:
                logger.warning(f"Ref error: {e}")

        # =========================
        # PRIVILEGE UX (CREATOR & ADMIN)
        # =========================
        if is_admin or is_vip:
            # Dinamik sarlavha tanlash[cite: 16]
            if user_id == config.CREATOR_ID:
                header, icon = "Tizim Yaratuvchisi", "⚡"
            elif status == "admin":
                header, icon = "Administrator", "🛠"
            else:
                header, icon = "VIP Foydalanuvchi", "💎"

            text = (
                f"{icon} <b>Xush kelibsiz, {full_name}!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Statusingiz:</b> <code>{header}</code>\n"
                f"💰 <b>Balansingiz:</b> <code>{points} ball</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🚀 <b>Imtiyoz:</b> Barcha cheklovlar olib tashlangan."
            )

            return await message.answer(
                text=text,
                reply_markup=get_main_menu(user_id, is_vip, status),
                parse_mode="HTML"
            )

        # =========================
        # SUB CHECK (HIGH-LOAD OPTIMIZED)
        # =========================
        ok, missing = await check_subscription(bot, user_id, session)

        if not ok:
            text = (
                f"👋 <b>Assalomu alaykum, {full_name}!</b>\n\n"
                f"Botimizdan foydalanish uchun quyidagi kanallarga a'zo bo'lishingiz kerak. "
                f"Bu botning barqaror ishlashini ta'minlaydi 🚀\n\n"
                f"<i>Obuna bo'lib, pastdagi tekshirish tugmasini bosing:</i>"
            )
            
            return await message.answer(
                text=text,
                reply_markup=build_sub_keyboard(missing), 
                parse_mode="HTML"
            )

        # =========================
        # REGULAR SUCCESS UX
        # =========================
        text = (
            f"🎉 <b>Xush kelibsiz, {full_name}!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Hisobingiz:</b> Faol\n"
            f"💰 <b>Balansingiz:</b> <code>{points} ball</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Botdan foydalanish uchun menyuni tanlang:</b>"
        )

        return await message.answer(
            text=text,
            reply_markup=get_main_menu(user_id, is_vip, status),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Start handler error: {e}", exc_info=True)
        
        # Foydalanuvchi uchun chiroyli xatolik xabari[cite: 16]
        error_text = (
            "❌ <b>Texnik nosozlik!</b>\n\n"
            "Tizimda kutilmagan xatolik yuz berdi. "
            "Xavotir olmang, muammo qayd etildi va tuzatilmoqda 🛠\n\n"
            "🔄 <i>Iltimos, qaytadan /start buyrug'ini yuboring.</i>"
        )
        
        await message.answer(text=error_text, parse_mode="HTML")
# =========================
# CHANNEL REDIRECT (OPTIMIZED)
# =========================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def redirect_handler(callback: types.CallbackQuery, session: AsyncSession):
    """
    Kesh bilan optimallashtirilgan va xavfsiz redirect handler[cite: 12, 16].
    """
    await callback.answer() # Callback yuklanishini darhol to'xtatish
    
    # 1. CIRCUIT BREAKER (Sessiya xavfsizligi)
    if session is None or isinstance(session._session, type(None)):
        return await callback.answer(
            "⚠️ Tizimda texnik ishlar ketmoqda.\n"
            "Iltimos, 1 daqiqadan so'ng urinib ko'ring.",
            show_alert=True
        )

    try:
        ch_id = int(callback.data.split(":")[1])

        # 2. CACHE-FIRST STRATEGY (Tezkorlik uchun)
        # Avval keshdan faol kanallarni olamiz
        all_channels = await get_active_channels(session)
        channel_data = next((c for c in all_channels if c['id'] == ch_id), None)

        # 3. AGAR KESHDA BO'LMASA, BAZADAN QIDIRISH[cite: 12]
        if not channel_data:
            stmt = select(Channel).where(Channel.channel_id == ch_id, Channel.is_active.is_(True))
            channel = await session.scalar(stmt)
            if channel:
                channel_data = {"title": channel.title, "url": channel.url}
        
        if not channel_data or not channel_data.get("url"):
            return await callback.answer(
                "❌ Kanal topilmadi yoki o'chirilgan.", 
                show_alert=True
            )

        # 4. PREMIUM UX DIZAYN
        text = (
            f"📢 <b>Kanal: {channel_data['title']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <b>Qadam:</b> Botdan to'liq foydalanish uchun "
            f"ushbu kanalga a'zo bo'lishingiz lozim.\n\n"
            f"<i>Obuna bo'lgach, 'Tasdiqlash' tugmasini bosing.</i>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Kanalga o'tish", url=channel_data['url'])],
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"check_sub:{ch_id}"),
                InlineKeyboardButton(text="⬅️ Orqaga", callback_data="check_sub:all")
            ]
        ])

        # Faqat o'zgargan bo'lsa edit qilish (API tejash)
        await callback.message.edit_text(
            text=text, 
            reply_markup=kb, 
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Redirect handler error: {e}", exc_info=True)
        await callback.answer(
            "❌ Kutilmagan xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.", 
            show_alert=True
        )
# =========================
# CHECK SUB (FAST PATH)
# =========================

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub(callback: types.CallbackQuery, user: dict, session: AsyncSession, bot: Bot):
    """
    Obunani tekshirish va referral mukofotlashning optimallashgan handleri.
    """
    # 1. Instant Feedback (UX uchun muhim)
    await callback.answer("⏳ Tekshirilmoqda, iltimos kuting...")

    user_id = callback.from_user.id
    
    # 2. Parallel Obunani tekshirish (Tezkorlik: High-Load)[cite: 16]
    ok, missing = await check_subscription(bot, user_id, session)

    if not ok:
        count = len(missing)
        return await callback.answer(
            f"⚠️ Obuna to'liq emas!\n"
            f"Yana {count} ta kanalga a'zo bo'lishingiz shart.", 
            show_alert=True
        )
    # Hozirgi holat
    
    # 3. Referral mantiqi (Repository orqali - Outbox mosligi)[cite: 8, 12]
    if not isinstance(session._session, type(None)):
        try:
            # UserRepository ball qo'shish va Outbox event yaratishni o'z ichiga oladi[cite: 8]
            # referred_by ni tozalash va ochko berish bir tranzaksiyada bajariladi
            reward_sent, ref_id = await UserRepository.process_referral_reward(session, user_id, amount=10)
            
            if reward_sent:
                # Referrerga bildirishnoma (Fonda bajariladi)[cite: 16]
                asyncio.create_task(
                    bot.send_message(
                        ref_id, 
                        "🎊 <b>Yangi muvaffaqiyat!</b>\n"
                        "Siz taklif qilgan foydalanuvchi obuna bo'ldi: <b>+10 ball</b> 🔥",
                        parse_mode="HTML"
                    )
                )
        except Exception as e:
            logger.error(f"Referral reward logic error: {e}")

    # 4. Success UX (Premium dizayn)[cite: 16]
    status = user.get("status", "user")
    is_vip = user.get("is_vip", False)
    
    # Eskisini tozalab, yangi menyuni chiqarish
    try:
        await callback.message.delete()
    except Exception:
        pass

    success_text = (
        f"✅ <b>Muvaffaqiyatli tasdiqlandi!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 <b>Xush kelibsiz, {callback.from_user.first_name}!</b>\n"
        f"Barcha cheklovlar olib tashlandi. Endi botdan to'liq foydalanishingiz mumkin.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 <b>Asosiy menyu orqali davom eting:</b>"
    )

    await callback.message.answer(
        text=success_text,
        reply_markup=get_main_menu(user_id, is_vip, status),
        parse_mode="HTML"
    )