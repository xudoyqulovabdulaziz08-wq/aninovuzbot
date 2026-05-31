import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from config import config
from keyboards.inline import admin_panel_kb, creator_panel_kb

router = Router()
logger = logging.getLogger(__name__)


# ========================================================================
# ⚙️ 1. SC ADMIN (JONINLAR) BOSHQARUV PANELI
# ========================================================================
@router.message(F.text == "⚙️ SC ADMIN PANEL")
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(event: types.Message | types.CallbackQuery, state: FSMContext):
    if state:
        await state.clear()
    
    # Kelajakda Middleware yoki DB orqali haqiqiy statusni olishingiz mumkin
    user_id = event.from_user.id
    user_status = "admin" 
    
    kb = admin_panel_kb(user_id=user_id, user_status=user_status)
    
    text = (
        "╔═════════ 🛡 ═════════╗\n"
        "   ⚙️ <b>JONINLAR PANELI</b> ⚙️\n"
        "╚═════════ 🛡 ═════════╝\n\n"
        f"Hurmatli Jonin (Admin), <b>{event.from_user.full_name}</b>!\n"
        "Bot xavfsizligi, tartibi va klan a'zolari nazorati sizning qo'lingizda. "
        "Iltimos, kerakli boshqaruv bo'limini tanlang ⚔️"
    )

    try:
        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        elif isinstance(event, types.CallbackQuery):
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Admin panel xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Admin panel kutilmagan xatolik: {e}")
    finally:
        # Callback kelganda miltillash va qotib qolishni oldini olish
        if isinstance(event, types.CallbackQuery):
            await event.answer("🛡 Joninlar paneli yuklandi")


# ========================================================================
# 👑 2. CREATOR (OLIY KAGE) BOSHQARUV PANELI
# ========================================================================
@router.message(F.text == "👑 CREATOR PANEL")
@router.callback_query(F.data == "creator_panel")
async def creator_panel_handler(event: types.Message | types.CallbackQuery, state: FSMContext):
    if state:
        await state.clear()
        
    user_id = event.from_user.id

    # 1. Ruxsat tekshiruvi: Faqatgina Creator (Siz) kira olasiz
    if user_id != config.CREATOR_ID:
        error_text = "🚫 Bu yashirin hududga faqatgina Oliy Kage (Creator) kira oladi!"
        if isinstance(event, types.CallbackQuery):
            await event.answer(error_text, show_alert=True)
        else:
            await event.answer(error_text)
        return

    kb = creator_panel_kb(creator_id=user_id)

    text = (
        "╔═════════ 👑 ═════════╗\n"
        "   👑 <b>OLIY KAGE PANELI</b> 👑\n"
        "╚═════════ 👑 ═════════╝\n\n"
        f"Salom Boss, <b>{event.from_user.full_name}</b>! 🏯\n\n"
        "Sizda botning barcha yashirin tizimlari, DB ma'lumotlari va to'liq "
        "boshqaruv imkoniyatlari mavjud. Qanday hukm chiqaramiz?"
    )

    try:
        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        elif isinstance(event, types.CallbackQuery):
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Creator panel xatoligi: {e}")
    except Exception as e:
        logger.error(f"❌ Creator panel kutilmagan xatolik: {e}")
    finally:
        # Yuklanish tugadi
        if isinstance(event, types.CallbackQuery):
            await event.answer("👑 Kage paneli faollashdi")