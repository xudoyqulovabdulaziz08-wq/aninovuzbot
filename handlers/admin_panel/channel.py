
import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.filters.callback_data import CallbackData


from config import config
from middlewares.db_middleware import SafeSession
from database.repository import ChannelRepository
from keyboards.inline import admin_channels_kb  

class AdminChannelsState(StatesGroup):
    adding_channel = State()
    deleting_channel = State()
    broadcasting = State()


class ChannelsPageCallback(CallbackData, prefix="chan_page"):
    page: int

class ChannelDetailCallback(CallbackData, prefix="chan_view"):
    channel_id: int
    page: int

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










#===========================back_to_channels=============================#
#========================================================================#
# Barcha state lardan "admin_channels" ga qaytishni osonlashtirish
@router.callback_query(F.data == "back_admin_channels")
async def back_to_channels(callback: types.CallbackQuery, state: FSMContext):
    await state.clear() # Muhim: State ni tozalab, keyin menyuni ko'rsatamiz
    await admin_channels(callback, state) # Eski funksiyangizni chaqiramiz











