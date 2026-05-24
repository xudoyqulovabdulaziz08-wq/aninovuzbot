import logging
from typing import Optional, Tuple
from urllib.parse import quote  # 🔥 FIX: URL formatlash uchun shart

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Agarda rasmni alohida faylda (masalan, config) saqlasangiz, o'sha yerdan chaqiring
# Reklama bo'limi uchun alohida File ID ishlatsangiz bo'ladi
ADVERTISEMENT_PHOTO_FILE_ID = "AgACAgIAAxkBAAFKaZRqEX9aJdksu2s4ZBw2j7WiPwM7ewAC6xtrG851kUhC8OgMkhJIGAEAAwIAA3kAAzsE"

router = Router()
logger = logging.getLogger(__name__)


# ======================================================
# 📢 REKLAMA TARKIBINI SHAKLLANTIRUVCHI YORDAMCHI FUNKSIYA
# ======================================================
def get_adv_content(user: Optional[dict]) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Reklama matni va inline klaviaturasini dinamik shakllantiruvchi yordamchi funksiya.
    DRY prinsipiga ko'ra message va callback handlerlari uchun bir marta yoziladi.
    """
    if not user:
        user = {}

    user_id = user.get("user_id", 0)

    text = (
        "📢 <b>REKLAMA VA HAMKORLIK</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Botingiz yoki loyihangizni bizning auditoriyamizga "
        "ko'rsatmoqchimisiz? Biz sizga yordam beramiz! 🚀\n\n"
        "📝 <b>Reklama yuborish tartibi:</b>\n"
        "🔹 Tayyor reklama posti (Matn + Rasm/Video)\n"
        "🔹 Havolalar (Linklar) to'g'ri sozlanganligi\n"
        "🔹 Kerakli auditoriya va vaqt kelishuvi\n\n"
        "💡 <b>Nima uchun biz?</b>\n"
        "✅ Faol va real foydalanuvchilar\n"
        "✅ Hamyonbop narxlar\n"
        "✅ Tezkor joylashtirish\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💼 Admin sizga barcha ma'lumotlarni taqdim etadi:"
    )

    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, reklama bermoqchiman. ID: {user_id if user_id else 'Noma`lum'}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📩 Adminga ariza yuborish", url=admin_url)
        ]
        
        
    ])

    return text, kb


# ======================================================
# 📢 1-KIRISH: TEXTLI TUGMA BOSILGANDA (REPLY KEYBOARD)
# ======================================================
@router.message(F.text == "📢 Reklama berish")
async def advertisement_message(message: types.Message, state: FSMContext, user: Optional[dict] = None):
    """
    Reply klaviaturadan '📢 Reklama berish' tugmasi bosilganda ishlaydi.
    Keshdan olingan ma'lumotlar bilan ultra-tez (L1) javob beradi.
    """
    await state.clear()

    # 🔥 CRITICAL FIX: Agar middleware qandaydir sabab bilan user'ni bera olmasa, bot crash bo'lmaydi
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Adv Message). User ID: {message.from_user.id}")
        user = {"user_id": message.from_user.id}

    text, kb = get_adv_content(user)

    try:
        # Vizual jozibadorlik (UX) uchun rasm bilan yuborish variantini qo'shdim
        await message.answer_photo(
            photo=ADVERTISEMENT_PHOTO_FILE_ID,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except (TelegramBadRequest, Exception) as e:
        # Agar rasm yuklashda muammo bo'lsa (masalan File ID xato bo'lsa), faqat tekst o'zi ketadi
        logger.error(f"❌ answer_photo xatoligi (Adv), tekst rejimiga o'tildi: {e}")
        await message.answer(text=text, reply_markup=kb, parse_mode="HTML")


# ======================================================
# 🔄 2-KIRISH: ORTGA QAYTGANDA XABARNI EDIT QILISH
# ======================================================
@router.callback_query(F.data == "open_advertisement")
async def advertisement_callback(callback: types.CallbackQuery, state: FSMContext, user: Optional[dict] = None):
    """
    Agarda boshqa biror bo'lim ichidan inline 'Ortga' tugmasi bosilsa,
    ekranni o'chirmasdan reklama bo'limini tahrirlab yuklaydi.
    """
    await state.clear()

    # 🔥 CRITICAL FIX: Callback holatida ham xavfsiz user fallbeki
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Adv Callback). User ID: {callback.from_user.id}")
        user = {"user_id": callback.from_user.id}

    text, kb = get_adv_content(user)

    try:
        # Eski xabar turi (rasmli yoki matnli) ekanligiga qarab mos tahrirlash
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        # Xabarda o'zgarish bo'lmasa xato tashlamasligi uchun
        pass
    except Exception as e:
        logger.error(f"❌ Adv Callback edit xatoligi: {e}")

    await callback.answer()