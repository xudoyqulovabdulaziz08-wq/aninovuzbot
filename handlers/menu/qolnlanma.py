
import logging

from aiogram import types, F, Router

from sqlalchemy import select, desc
from database.models import DBUser

from config import config
from aiogram.fsm.context import FSMContext
from database.cache import valkey
from urllib.parse import quote
from aiogram.exceptions import TelegramBadRequest

GUIDE_PHOTO_FILE_ID = "AgACAgIAAxkBA..." # Telegram serveridagi yuklangan rasm File ID'si (Tezkor yuklanish uchun)

router = Router()
logger = logging.getLogger(__name__)

def get_guide_content(user: dict) -> tuple[str, types.InlineKeyboardMarkup]:
    """
    Qo'llanma matni va klaviaturasini dinamik shakllantiruvchi yordamchi funksiya.
    L1 kesh ma'lumotlaridan UXni oshirish uchun foydalanamiz.
    """
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
    raw_msg = f"Assalomu alaykum, yordam kerak. ID: {user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📩 Admin bilan bog'lanish", url=admin_url)
        ],
        [
            types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet"),
            types.InlineKeyboardButton(text="💎 VIP menyu", callback_data="buy_vip_menu"),
        ],
        [
            types.InlineKeyboardButton(text="🔗 Taklif havola", callback_data="get_ref_link")
        ]
    ])
    
    return text, kb


# 1-KIRISH: Matnli tugma bosilganda (Yangi xabar yuboriladi, rasm bilan)
@router.message(F.text == "❓ Qo'llanma")
async def help_page_message(message: types.Message, user: dict, state: FSMContext):
    """
    Reply klaviaturadan 'Qo'llanma' bosilganda ishlaydi.
    Rasm va dinamik tekst bilan ultra-tez (L1) javob beradi.
    """
    await state.clear()
    text, kb = get_guide_content(user)

    try:
        # UX uchun rasm bilan yuborish (Brending uchun zo'r vizual beradi)
        # Agar rasm hali yuklanmagan bo'lsa, shunchaki message.answer ishlatishingiz mumkin
        await message.answer_photo(
            photo=GUIDE_PHOTO_FILE_ID,
            caption=text,
            reply_markup=kb
        )
    except TelegramBadRequest:
        # Agar File ID xato bo'lsa yoki topilmasa, fallback rejimida oddiy tekst yuboriladi
        await message.answer(text=text, reply_markup=kb)


# 2-KIRISH: Boshqa bo'limlardan "Ortga" qaytganda xabarni tahrirlash (Edit message)
@router.callback_query(F.data == "open_guide")
async def help_page_callback(callback: types.CallbackQuery, user: dict, state: FSMContext):
    """
    Boshqa bo'limlardan (masalan, VIP menyudan) 'Ortga' tugmasi bosilganda
    ekranni o'chirmasdan qo'llanmani o'rniga tahrirlab qo'yadi.
    """
    await state.clear()
    text, kb = get_guide_content(user)
    
    try:
        # Agar eski xabar rasm bo'lsa caption o'zgaradi, matn bo'lsa text o'zgaradi
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text=text, reply_markup=kb)
    except TelegramBadRequest:
        # Agar xabarda o'zgarish bo'lmasa xatolik bermasligi uchun
        pass
    
    await callback.answer()