import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from config import config
from keyboards.inline import creator_admin_kb, creator_db_panel_kb

router = Router()
logger = logging.getLogger(__name__)

# CREATOR_ID'ni olamiz (Garchand bu qismda to'g'ridan-to'g'ri filtr qilinmasa ham, 
# kelajakda kerak bo'lishi mumkin)
CREATOR_ID = getattr(config, 'CREATOR_ID', 0)


# ========================================================================
# 👑 1. KAGE (CREATOR) ADMINLARNI BOSHQARISH PANELI
# ========================================================================
@router.callback_query(F.data == "creator_admin_panel")
async def creator_admin_panel_handler(callback: types.CallbackQuery, state: FSMContext):
    if state:
        await state.clear()
    
    kb = creator_admin_kb()
    
    text = (
        "╔═════════ 👑 ═════════╗\n"
        "   ⛩ <b>JONINLAR KENGASHI</b> ⛩\n"
        "╚═════════ 👑 ═════════╝\n\n"
        f"Oliy Kage, <b>{callback.from_user.full_name}</b> xush kelibsiz! 🏯\n\n"
        "Bu yerda siz klaningizdagi adminlarni (Joninlarni) tayinlashingiz, "
        "ularning vakolatlarini kengaytirishingiz yoki chetlatishingiz mumkin. ⚔️\n\n"
        "⚠️ <i>Ogohlantirish: Har bir qaroringiz qishloq taqdiriga ta'sir qiladi!</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Creator Admin panel xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Creator Admin panel kutilmagan xatolik: {e}")
    finally:
        # UX ni silliq qilish uchun answer doim finally ichida bo'lishi kerak
        await callback.answer("👑 Joninlar kengashi ochildi")


# ========================================================================
# 🗄 2. KAGE (CREATOR) MA'LUMOTLAR BAZASI (DB) PANELI
# ========================================================================
@router.callback_query(F.data == "creator_db_panel")
async def creator_db_panel_handler(callback: types.CallbackQuery, state: FSMContext):
    if state:
        await state.clear()
    
    kb = creator_db_panel_kb() 
    
    text = (
        "╔═════════ 🗄 ═════════╗\n"
        "   📜 <b>MAXFIY BAZA (DB)</b> 📜\n"
        "╚═════════ 🗄 ═════════╝\n\n"
        "Barcha shinobilarning maxfiy ma'lumotlari saqlanadigan xazina. 👁‍🗨\n\n"
        "Siz bu yerda foydalanuvchilar axborotini kuzatishingiz, "
        "statistikalarni ko'rishingiz va tizim barqarorligini ta'minlash "
        "uchun jutsu (buyruqlar) ishlatishingiz mumkin. 🔮\n\n"
        "⚠️ <i>Ehtiyotkorlik bilan foydalaning, ma'lumotlar yo'qolishi xavfli!</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Creator DB panel xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Creator DB panel kutilmagan xatolik: {e}")
    finally:
        await callback.answer("🗄 Maxfiy ma'lumotlar bazasi ochildi")