
import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import admin_channels_kb

class AdminChannelsState(StatesGroup):
    adding_channel = State()
    deleting_channel = State()
    broadcasting = State()


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')



#============================admin_channels==============================#
#========================================================================#
@router.callback_query(F.data == "admin_channels")
async def admin_channels(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    text = (
        "📢 <b>KANALLAR BO'LIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Boshqaruv paneli yuklandi.\n"
        "Kanallarni boshqarishingiz mumkin."
    )
    
    kb = admin_channels_kb()
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Admin kanallar xatosi: {e}")
    finally:
        # Bitta javob yetarli
        await callback.answer("📢 Kanallar bo'limi yuklandi")





#============================admin_channels==============================#
#========================================================================#
@router.callback_query(F.data == "add_channel")
async def add_channel(callback: types.CallbackQuery, state: FSMContext):
    # 1. Holatni o'rnatish
    await state.set_state(AdminChannelsState.adding_channel)
    
    # 2. Yangi matn va klaviatura
    text = "➕ <b>KANAL QO'SHISH</b>\n\nKanal ID yoki username (misol: @kanal_nomi) yuboring:"
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_admin_channels"))
    
    # 3. Matnni va tugmani bir vaqtda yangilash (foydalanuvchi uchun tushunarliroq)
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Admin kanallar xatosi: {e}")
            
    
    await callback.answer("Kanal qo'shish rejimiga o'tildi. Kanal ID yoki username yuboring.")




#===========================back_to_channels=============================#
#========================================================================#
# Barcha state lardan "admin_channels" ga qaytishni osonlashtirish
@router.callback_query(F.data == "back_admin_channels")
async def back_to_channels(callback: types.CallbackQuery, state: FSMContext):
    await state.clear() # Muhim: State ni tozalab, keyin menyuni ko'rsatamiz
    await admin_channels(callback, state) # Eski funksiyangizni chaqiramiz




