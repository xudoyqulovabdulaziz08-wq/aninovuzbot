import logging
from typing import Optional, Tuple
from urllib.parse import quote  # 🔥 FIX: URL encode uchun shart!

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Config yoki main'dan keladigan o'zgaruvchilar (misol tariqasida)
from config import config  

router = Router(name="guide_router")
logger = logging.getLogger(__name__)

# 🔥 Loyihangizdagi rasm File ID'sini shu yerga qo'ying yoki config'dan oling
GUIDE_PHOTO_FILE_ID = getattr(config, "GUIDE_PHOTO_FILE_ID", "AgACAgIAAxkBAAFKaWtqEX4ZZBnoIqvg4b1uXliNoJs-iAAC3xtrG851kUgpJfPIbaWCxgEAAwIAA3kAAzsE") 


# ======================================================
# 🔥 DINAMIK TARKIB SHAKLLANTIRUVCHI YORDAMCHI FUNKSIYA
# ======================================================
def get_guide_content(user: Optional[dict]) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Qo'llanma matni va klaviaturasini dinamik shakllantiruvchi yordamchi funksiya.
    L1 kesh ma'lumotlaridan UXni oshirish uchun foydalanamiz.
    """
    # Middleware'dan user kelmasa fallback default qiymatlar
    if not user:
        user = {}

    user_id = user.get("user_id", 0)
    current_points = user.get("points", 0)
    is_vip = user.get("is_vip", False)
    
    # VIP status dizayni
    vip_status = "💎 Faol" if is_vip else "❌ Mavjud emas"

    text = (
        "❓ <b>FOYDALANISH QO'LLANMASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Botingizdan samarali foydalanishingiz uchun barcha "
        "imkoniyatlar haqida qisqacha ma'lumot: 📑\n\n"
        "👤 <b>Shaxsiy kabinet:</b>\n"
        "Profilingiz, joriy ballaringiz va VIP holatini kuzatish.\n\n"
        "🏆 <b>Reyting:</b>\n"
        "Eng ko'p ball to'plagan va faol foydalanuvchilar TOP ro'yxati.\n\n"
        "💎 <b>VIP tizimi:</b>\n"
        "Cheklovsiz kirish, reklamalardan xoli va maxsus status.\n\n"
        "🎯 <b>Referal dasturi:</b>\n"
        "Do'stlaringizni taklif qilib, har bir faol foydalanuvchi uchun ball yig'ing.\n\n"
        "📊 <b>Sizning holatingiz:</b>\n"
        f"└ ✨ Ballaringiz: <code>{current_points} XP</code>\n"
        f"└ 👑 VIP status: <b>{vip_status}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📩 <b>Yordam kerakmi?</b>\n"
        "Savollar yoki takliflar bo'lsa, adminga murojaat qiling:"
    )

    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, yordam kerak. ID: {user_id if user_id else 'Noma/lum'}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📩 Admin bilan bog'lanish", url=admin_url)
        ]
    ])
    
    return text, kb


# ======================================================
# 📑 1-KIRISH: TEXTLI TUGMA BOSILGANDA (RASM BILAN YUBORISH)
# ======================================================
@router.message(F.text == "❓ Qo'llanma")
async def help_page_message(message: types.Message, state: FSMContext, user: Optional[dict] = None):
    """
    Reply klaviaturadan 'Qo'llanma' bosilganda ishlaydi.
    Rasm va dinamik tekst bilan ultra-tez (L1) javob beradi.
    """
    await state.clear()
    
    # 🔥 CRITICAL FIX: Agar middleware'dan user kelmasa, fonga xabar beramiz lekin bot o'chmaydi
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Message). User ID: {message.from_user.id}")
        user = {"user_id": message.from_user.id}

    text, kb = get_guide_content(user)

    try:
        # UX uchun rasm bilan yuborish
        await message.answer_photo(
            photo=GUIDE_PHOTO_FILE_ID,
            caption=text,
            reply_markup=kb
        )
    except (TelegramBadRequest, Exception) as e:
        # Rasm o'chib ketgan bo'lsa yoki File ID xato bo'lsa fallback: oddiy tekst yuboriladi
        logger.error(f"❌ answer_photo xatoligi, tekst rejimiga o'tildi: {e}")
        await message.answer(text=text, reply_markup=kb)


# ======================================================
# 🔄 2-KIRISH: ORTGA QAYTGANDA XABARNI TAHRIRLASH
# ======================================================
@router.callback_query(F.data == "open_guide")
async def help_page_callback(callback: types.CallbackQuery, state: FSMContext, user: Optional[dict] = None):
    """
    Boshqa bo'limlardan 'Ortga' tugmasi bosilganda ekranni o'chirmasdan
    qo'llanmani o'rniga tahrirlab qo'yadi.
    """
    await state.clear()
    
    # 🔥 CRITICAL FIX: Callback holatida ham user'ni xavfsiz tekshirish
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Callback). User ID: {callback.from_user.id}")
        user = {"user_id": callback.from_user.id}

    text, kb = get_guide_content(user)
    
    try:
        # Agar eski xabar rasm bo'lsa caption o'zgaradi, matn bo'lsa text o'zgaradi
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text=text, reply_markup=kb)
    except TelegramBadRequest:
        # Agar xabarda o'zgarish bo'lmasa, Aiogram xato tashlamasligi uchun yopamiz
        pass
    except Exception as e:
        logger.error(f"❌ Callback edit xatoligi: {e}")
    
    await callback.answer()