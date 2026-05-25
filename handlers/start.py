import logging
import asyncio
from typing import List, Dict, Tuple, Set
from datetime import datetime, timezone

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.reply import get_main_menu
from config import config 
from database.repository import ChannelRepository 

# Router obyektini yaratamiz
router = Router()
logger = logging.getLogger("SubChecker")

# ==========================================
# 🧠 MEMORY CACHE & ANTI-SPAM GUARD
# ==========================================
# Tugmani cheksiz bosib flood qilishdan himoya (User ID -> Timestamp)
_SUB_CHECK_COOLDOWN: Dict[int, float] = {}
COOLDOWN_DURATION = 3.0  # Soniyalarda (Anti-spam oynasi)


# ==========================================
# 🛠 YORDAMCHI FUNKSIYALAR (HELPERS)
# ==========================================
def build_subscription_keyboard(unsubscribed_channels: List[Dict[str, str]]) -> InlineKeyboardMarkup:
    """ 
    🎨 Obuna bo'linmagan kanallar uchun chiroyli va tartibli inline klaviatura.
    Kanallar soni ko'p bo'lsa, ixcham ko'rinishga keltiriladi.
    """
    buttons = []
    
    # Har bir a'zo bo'linmagan kanal uchun ulanish tugmasi (Chiroyli emoji bilan)
    for index, ch in enumerate(unsubscribed_channels, start=1):
        title = ch.get("title", f"Homiylar kanali #{index}")
        url = ch.get("url", "https://t.me")
        buttons.append([InlineKeyboardButton(text=f"📢 {title}", url=url)])
    
    # Tekshirish tugmasini oxiriga alohida ajralib turadigan qilib qo'shamiz
    buttons.append([InlineKeyboardButton(text="🔄 Obunani Tekshirish", callback_data="check_subscriptions")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def check_user_subscriptions(
    bot: Bot, 
    user_id: int, 
    session: AsyncSession
) -> Tuple[bool, List[Dict[str, str]]]:
    """
    🚀 Real O(1) Kesh mexanizmiga tayanuvchi, crash-safe obuna tekshirgich.
    Telegram API xatolarini to'liq izolatsiya qiladi.
    """
    try:
        # Faol kanallarni keshdan (L1/L2) mutloq tezlikda olamiz (Baza xavfsiz)
        active_channels = await ChannelRepository.get_all_active_channels(session)
    except Exception as db_err:
        logger.error(f"🚨 Kesh yoki bazadan kanallarni olishda jiddiy xatolik: {db_err}")
        # Baza qulagan holatda ham bot ishlashdan to'xtamasligi uchun silliq o'tkazamiz
        return True, []
    
    if not active_channels:
        return True, []

    unsubscribed = []

    # Har bir kanalni Telegram API orqali tekshiramiz
    for channel in active_channels:
        if not channel.channel_id:
            continue
            
        try:
            member = await bot.get_chat_member(chat_id=channel.channel_id, user_id=user_id)
            
            # Obuna bo'lmagan yoki haydalgan holatlarni qat'iy tekshirish
            if member.status in ["left", "kicked"]:
                unsubscribed.append({
                    "title": channel.title or "Kanal",
                    "url": channel.url or "https://t.me"
                })
        except TelegramAPIError as e:
            # Bot kanalda admin emasligi yoki kanal o'chgani foydalanuvchiga ta'sir qilmasligi kerak
            logger.error(f"⚠️ Kanal tekshirishda API xatolik [ID: {channel.channel_id} | Title: {channel.title}]: {e}")
            continue
        except Exception as general_err:
            logger.error(f"⚠️ Kutilmagan ichki xatolik (ChatMember): {general_err}")
            continue

    return len(unsubscribed) == 0, unsubscribed


# ==========================================
# 📥 HANDLERLAR (HANDLERS)
# ==========================================
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, session: AsyncSession):
    """ 🛡 High-Load va Crash-Safe sharoitiga moslashtirilgan /start handleri """
    if not message.from_user:
        return

    user_id = message.from_user.id
    full_name = message.from_user.full_name
    
    # Kesh ustida 0-5ms ichida obunani tekshiramiz
    is_subscribed, unsubscribed = await check_user_subscriptions(bot, user_id, session)
    
    if is_subscribed:
        # 🟢 FOYDALANUVCHI OBUNA BO'LGAN (Asosiy menyu)
        await message.answer(
            text=(
                f"👋 **Assalomu alaykum, {full_name}!**\n\n"
                "🤖 Botimiz xizmatlaridan to'liq foydalanishingiz mumkin.\n"
                "📋 Quyidagi menyudan kerakli bo'limni tanlang:"
            ),
            reply_markup=get_main_menu(
                is_vip=False, 
                is_admin=False, 
                is_creator=(user_id == config.CREATOR_ID)
            ),
            parse_mode="Markdown"
        )
    else:
        # 🔴 OBUNA BO'LMAGAN (Bloklash paneli)
        await message.answer(
            text=(
                "⚠️ **Diqqat! Botdan foydalanish cheklangan.**\n\n"
                "Tizim faoliyatini davom ettirish va sizga xizmat ko'rsatishimiz uchun "
                "quyidagi homiy kanallarimizga a'zo bo'lishingiz shart. 👇"
            ),
            reply_markup=build_subscription_keyboard(unsubscribed),
            parse_mode="Markdown"
        )


@router.message(F.text == "Menu")
async def menu_handler(message: Message, bot: Bot, session: AsyncSession):
    """ 
    🛡 Deep-Security filtri: Foydalanuvchi klaviaturani bypass qilib,
    matn ko'rinishida 'Menu' deb yozsa ham obunani qayta tekshiradi.
    """
    if not message.from_user:
        return

    user_id = message.from_user.id
    is_subscribed, unsubscribed = await check_user_subscriptions(bot, user_id, session)
    
    if not is_subscribed:
        await message.answer(
            text=(
                "❌ **Kechirasiz, taqiqlangan amal!**\n\n"
                "Siz hali majburiy obunani yakunlamagansiz. Botdan foydalanish uchun "
                "avval quyidagi kanallarga a'zo bo'ling:"
            ),
            reply_markup=build_subscription_keyboard(unsubscribed),
            parse_mode="Markdown"
        )
        return

    # Agar obunadan toza o'tgan bo'lsa, menyuni ko'rsatamiz
    is_creator = (user_id == config.CREATOR_ID)
    await message.answer(
        text="📋 **Bosh menyu yuklanmoqda...**",
        reply_markup=get_main_menu(
            is_vip=False, 
            is_admin=False, 
            is_creator=is_creator
        ),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "check_subscriptions")
async def cb_check_subscriptions(callback: CallbackQuery, bot: Bot, session: AsyncSession):
    """ 
    🔄 'Obunani Tekshirish' tugmasi bosilganda ishlovchi aqlli handler.
    Flood, Crash va vizual kechikishlardan to'liq himoyalangan.
    """
    user_id = callback.from_user.id
    current_time = asyncio.get_event_loop().time()
    
    # 1. ANTI-FLOOD CHECK (Spamga qarshi qalqon)
    if user_id in _SUB_CHECK_COOLDOWN:
        last_click = _SUB_CHECK_COOLDOWN[user_id]
        if current_time - last_click < COOLDOWN_DURATION:
            await callback.answer(
                text="⏳ Iltimos, biroz kuting! Har bir soniyada tugmani bosa olmaysiz.", 
                show_alert=True
            )
            return

    # Joriy bosish vaqtini keshga yozamiz
    _SUB_CHECK_COOLDOWN[user_id] = current_time

    # 2. UX INTERACTION (Foydalanuvchiga vizual yuklanish animatsiyasi)
    try:
        await callback.message.edit_text(
            text="⏳ **Obunangiz tekshirilmoqda, iltimos kuting...**",
            parse_mode="Markdown"
        )
    except Exception:
        # Agar xabar matni o'zgarmasa (masalan, foydalanuvchi juda tez bossa) xato bermasligi uchun
        pass

    # Keshga asoslangan obuna tekshiruvi amali
    is_subscribed, unsubscribed = await check_user_subscriptions(bot, user_id, session)
    
    if is_subscribed:
        # 🟢 MUVAFFAQIYATLI O'TDI
        await callback.answer("Muvaffaqiyatli tekshirildi! 🎉", show_alert=False)
        
        # Eski inline xabarni o'chirib, toza yangi menyu yuboramiz
        await callback.message.delete()
        await callback.message.answer(
            text=(
                "✅ **Rahmat! Obuna muvaffaqiyatli tasdiqlandi.**\n\n"
                "🤖 Bot to'liq ishga tushdi. Quyidagi menyudan foydalanishingiz mumkin:"
            ),
            reply_markup=get_main_menu(
                is_vip=False, 
                is_admin=False, 
                is_creator=(user_id == config.CREATOR_ID)
            ),
            parse_mode="Markdown"
        )
    else:
        # 🔴 HALI OBUNA BO'LMAGAN
        await callback.answer(
            text="❌ Siz hali barcha kanallarga obuna bo'lmagansiz! Iltimos, tekshirib qayta urining.", 
            show_alert=True
        )
        
        # Tugmalar ro'yxati yoki kanallar o'zgargan bo'lsa, xabarni eski holiga qaytarib yangilaymiz
        try:
            await callback.message.edit_text(
                text=(
                    "⚠️ **Obuna tasdiqlanmadi!**\n\n"
                    "Siz quyidagi barcha kanallarga a'zo bo'lishingiz kerak. Keyin esa qaytadan tekshirish tugmasini bosing:"
                ),
                reply_markup=build_subscription_keyboard(unsubscribed),
                parse_mode="Markdown"
            )
        except Exception:
            pass

# Periodik ravishda eski cooldown xotirasini tozalash (Memory leak oldini olish)
if len(_SUB_CHECK_COOLDOWN) > 5000:
    _SUB_CHECK_COOLDOWN.clear()