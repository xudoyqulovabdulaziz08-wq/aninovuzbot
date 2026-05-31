import logging
from typing import Optional, Tuple
from urllib.parse import quote  # 🔥 URL formatlash uchun shart

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Loyihangizdagi rasm File ID'sini shu yerga qo'ying yoki config'dan oling
ADVERTISEMENT_PHOTO_FILE_ID = "AgACAgIAAxkBAAFKl-tqFC9XZppHrJDZTjAo4VWqkMpx7gAC2htrG851kUgFMwM8MnFuAwEAAwIAA3cAAzsE"

router = Router()
logger = logging.getLogger(__name__)


# ======================================================
# 📢 REKLAMA TARKIBINI SHAKLLANTIRUVCHI YORDAMCHI FUNKSIYA
# ======================================================
def get_adv_content(user: Optional[dict]) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Reklama matni va inline klaviaturasini dinamik shakllantiruvchi yordamchi funksiya.
    Anime Themed UX/UI 🎌
    """
    if not user:
        user = {}

    user_id = user.get("user_id", "Noma'lum")

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   📢  <b>HAMKORLIK & REKLAMA</b> 📢\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "O'z loyihangiz, botingiz yoki kanalingizni bizning ulkan "
        "<b>Nakama (Auditoriyamiz)</b>ga namoyish etishni xohlaysizmi? Biz sizga yordam beramiz! 🚀\n\n"
        "📜 <b>Reklama joylash tartibi:</b>\n"
        "🔹 Tayyor ijodiy post <i>(Matn + Rasm/Video)</i>\n"
        "🔹 To'g'ri sozlangan yashirin muhrlar <i>(Linklar)</i>\n"
        "🔹 Klanlararo kelishilgan vaqt va reja\n\n"
        "✨ <b>Nima uchun aynan biz?</b>\n"
        "✅ Doimiy faol va tirik ninjalar jamoasi\n"
        "✅ Hamyonbop oltinlar <i>(Narxlar)</i>\n"
        "✅ Joylashtirish <b>Shunshin no Jutsu</b> tezligida ⚡️\n\n"
        "═════════ ⛩ ═════════\n"
        "👨‍💼 <b>Kage (Admin)</b> sizga barcha maxfiy ma'lumotlarni taqdim etadi:"
    )

    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, reklama bermoqchiman. ID: {user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📩 Kage bilan bog'lanish", url=admin_url)
        ]
        
    ])

    return text, kb


# ======================================================
# 📢 1-KIRISH: TEXTLI TUGMA BOSILGANDA (REPLY KEYBOARD)
# ======================================================
@router.message(F.text == "📢 Reklama berish")
async def advertisement_message(message: types.Message, state: FSMContext, user: Optional[dict] = None):
    if state:
        await state.clear()

    # 🔥 CRITICAL FIX: Agar middleware foydalanuvchini bera olmasa fallback
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Adv Message). User ID: {message.from_user.id}")
        user = {"user_id": message.from_user.id}

    text, kb = get_adv_content(user)

    try:
        await message.answer_photo(
            photo=ADVERTISEMENT_PHOTO_FILE_ID,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except (TelegramBadRequest, Exception) as e:
        logger.error(f"❌ answer_photo xatoligi (Adv), tekst rejimiga o'tildi: {e}")
        await message.answer(text=text, reply_markup=kb, parse_mode="HTML")


# ======================================================
# 🔄 2-KIRISH: ORTGA QAYTGANDA XABARNI EDIT QILISH
# ======================================================
@router.callback_query(F.data == "open_advertisement")
async def advertisement_callback(callback: types.CallbackQuery, state: FSMContext, user: Optional[dict] = None):
    if state:
        await state.clear()

    # 🔥 CRITICAL FIX: Callback holatida ham xavfsiz user fallbeki
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Adv Callback). User ID: {callback.from_user.id}")
        user = {"user_id": callback.from_user.id}

    text, kb = get_adv_content(user)

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        # Matn o'zgarmagan holatdagi oddiy ogohlantirishni chetlab o'tamiz, boshqasini log qilamiz
        if "message is not modified" not in str(e):
            logger.error(f"❌ Adv Callback edit xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Kutilmagan Callback xatoligi: {e}")
    finally:
        await callback.answer()