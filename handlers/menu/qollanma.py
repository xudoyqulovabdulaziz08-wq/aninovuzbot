import logging
from typing import Optional, Tuple
from urllib.parse import quote  # 🔥 URL encode uchun shart!

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# Config yoki main'dan keladigan o'zgaruvchilar
from config import config  

router = Router()
logger = logging.getLogger(__name__)

# 🔥 Loyihangizdagi rasm File ID'si
GUIDE_PHOTO_FILE_ID = getattr(config, "GUIDE_PHOTO_FILE_ID", "AgACAgIAAxkBAAFKl-tqFC9XZppHrJDZTjAo4VWqkMpx7gAC2htrG851kUgFMwM8MnFuAwEAAwIAA3cAAzsE") 


# ======================================================
# 🔥 DINAMIK TARKIB SHAKLLANTIRUVCHI YORDAMCHI FUNKSIYA
# ======================================================
def get_guide_content(user: Optional[dict]) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    Qo'llanma matni va klaviaturasini dinamik shakllantiruvchi yordamchi funksiya.
    Anime Themed UX/UI 🎌
    """
    if not user:
        user = {}

    user_id = user.get("user_id", "Noma'lum")

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   📜 <b>BOT QO'LLANMASI</b> 📜\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Sarguzashtlaringizni osonlashtirish uchun barcha "
        "imkoniyatlar bilan tanishing, Nakama! 🌸\n\n"
        "🏯 <b>Shaxsiy kabinet:</b>\n"
        "<blockquote expandable>Profilingiz, to'plagan energiyangiz (ballar) va darajangizni kuzatish.</blockquote>\n"
        "🏆 <b>Reyting:</b>\n"
        "<blockquote expandable>Eng kuchli ninjalar va TOP foydalanuvchilar ro'yxati.</blockquote>\n"
        "💎 <b>Premium (VIP):</b>\n"
        "<blockquote expandable>Cheklovsiz kirish, reklamalarsiz muhit va maxsus imtiyozlar.</blockquote>\n"
        "👥 <b>Referal:</b>\n"
        "<blockquote expandable>Do'stlaringizni taklif qilib, har bir faol do'stingiz uchun energiya yig'ing.</blockquote>\n"
        "═════════ ⛩ ═════════\n"
        "📩 <b>Yordam kerakmi?</b>\n"
        "Savollar yoki takliflar bo'lsa, Admin ga murojaat qiling:"
    )

    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, yordam kerak. ID: {user_id}"
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
    await state.clear()
    
    # 🔥 CRITICAL FIX: Agar middleware'dan user kelmasa, fonga xabar beramiz
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Message). User ID: {message.from_user.id}")
        user = {"user_id": message.from_user.id}

    text, kb = get_guide_content(user)

    try:
        await message.answer_photo(
            photo=GUIDE_PHOTO_FILE_ID,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"  # 🛠 FIX: HTML teglari ishlashi uchun qo'shildi
        )
    except (TelegramBadRequest, Exception) as e:
        logger.error(f"❌ answer_photo xatoligi, tekst rejimiga o'tildi: {e}")
        await message.answer(
            text=text, 
            reply_markup=kb, 
            parse_mode="HTML"  # 🛠 FIX
        )


# ======================================================
# 🔄 2-KIRISH: ORTGA QAYTGANDA XABARNI TAHRIRLASH
# ======================================================
@router.callback_query(F.data == "open_guide")
async def help_page_callback(callback: types.CallbackQuery, state: FSMContext, user: Optional[dict] = None):
    await state.clear()
    
    # 🔥 CRITICAL FIX: Callback holatida ham user'ni xavfsiz tekshirish
    if user is None:
        logger.warning(f"⚠️ DbMiddleware 'user' bera olmadi (Callback). User ID: {callback.from_user.id}")
        user = {"user_id": callback.from_user.id}

    text, kb = get_guide_content(user)
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text, 
                reply_markup=kb, 
                parse_mode="HTML"  # 🛠 FIX
            )
        else:
            await callback.message.edit_text(
                text=text, 
                reply_markup=kb, 
                parse_mode="HTML"  # 🛠 FIX
            )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"❌ TelegramBadRequest edit xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Callback edit kutilmagan xatolik: {e}")
    
    await callback.answer()