import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from config import config
from keyboards.inline import get_ranked_kb

router = Router()
logger = logging.getLogger(__name__)


# ========================================================================
# 🌟 REYTING ASOSIY MENYUSI (MESSAGE & CALLBACK)
# ========================================================================
@router.message(F.text == "🌟 Reyting")
@router.callback_query(F.data == "reyting_menu")
async def ranked_menu(event: types.Message | types.CallbackQuery, state: FSMContext):
    """
    Reyting bo'limining bosh menyusi.
    Foydalanuvchi matn yozganda yoki 'Ortga' tugmasini bosganda ultra-tez ochiladi.
    """
    if state:
        await state.clear()

    kb = get_ranked_kb()
    
    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🌟 <b>REYTING CHODIRI</b> 🌟\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Buyuk ninjalar va eng sara afsonalar olamiga xush kelibsiz! "
        "Kim eng kuchli ekanini bilish vaqti keldi: 🔍\n\n"
        "🎬 <b>Anime Shon-sharafi:</b>\n"
        "└ <i>Eng ko'p ko'rilgan va ommabop animelar TOP ro'yxati</i>\n\n"
        "🏆 <b>Top Shinobilar:</b>\n"
        "└ <i>Eng faol va yuqori energiyaga (ballarga) ega foydalanuvchilar</i>\n\n"
        "⚡️ <i>Klan muhandislarimiz yangi maxfiy tizimlar ustida ishlamoqda...</i>"
    )

    try:
        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        elif isinstance(event, types.CallbackQuery):
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Reyting menyu edit xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Reyting menyuda kutilmagan xatolik: {e}")
    finally:
        if isinstance(event, types.CallbackQuery):
            await event.answer()


# ========================================================================
# 🎬 ANIME REYTINGI BO'LIMI (TEZ ORADA)
# ========================================================================
@router.callback_query(F.data == "Anime_ranked")
async def anime_ranked(callback: types.CallbackQuery, state: FSMContext):
    """ Animelar reytingi bo'limi (Hozircha yopiq) """
    if state:
        await state.clear()

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🎬 <b>ANIME REYTINGI</b> 🎬\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Afsuski, bu maxfiy varoq hali to'liq ochilmadi! 📜\n\n"
        "❗️ Hozircha eng ommabop animelar reytingini ko'rish jutsusi tayyor emas. "
        "Tez orada klan muhandislari uni yakunlashadi. Yangilanishlarni kuting, Nakama! 🌸"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⛩ Ortga qaytish", callback_data="reyting_menu"))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Anime ranked xatosi: {e}")
    except Exception as e:
        logger.error(f"❌ Anime ranked kutilmagan xatosi: {e}")
    finally:
        await callback.answer("🎬 Anime reytingi tez orada qo'shiladi!")


# ========================================================================
# 🏆 FOYDALANUVCHILAR REYTINGI BO'LIMI (TEZ ORADA) - FIX BUGS!
# ========================================================================
@router.callback_query(F.data == "User_ranked")
async def user_ranked(callback: types.CallbackQuery, state: FSMContext):
    """ 
    Foydalanuvchilar reytingi bo'limi (Hozircha yopiq).
    🛠 FIX: Oldingi kodda bo'lgan nusxa ko'chirish (Anime ranked xatolari) butkul tuzatildi!
    """
    if state:
        await state.clear()

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🏆 <b>SHINOBI REYTINGI</b> 🏆\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Eng kuchli ninjalar ro'yxati hali shakllantirilmoqda! ⚔️\n\n"
        "❗️ Hozircha yuqori ballga ega faol foydalanuvchilar reytingini ko'rish imkoniyati mavjud emas. "
        "Buyuk ninja urushiga tayyorgarlik ko'rilmoqda. O'z energiyangizni yig'ishda davom eting! 🌸"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⛩ Ortga qaytish", callback_data="reyting_menu"))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        # Xabarda o'zgarish bo'lmagan holatni xavfsiz chetlab o'tamiz
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ User ranked xatosi: {e}")  # 🛠 FIX: Log to'g'rilandi
    except Exception as e:
        logger.error(f"❌ User ranked kutilmagan xatosi: {e}")
    finally:
        await callback.answer("🏆 Shinobilar reytingi tez orada qo'shiladi!")  