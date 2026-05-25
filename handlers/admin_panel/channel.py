
import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import Message, CallbackQuery

from config import config
from database.repository import ChannelRepository
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










#===========================back_to_channels=============================#
#========================================================================#
# Barcha state lardan "admin_channels" ga qaytishni osonlashtirish
@router.callback_query(F.data == "back_admin_channels")
async def back_to_channels(callback: types.CallbackQuery, state: FSMContext):
    await state.clear() # Muhim: State ni tozalab, keyin menyuni ko'rsatamiz
    await admin_channels(callback, state) # Eski funksiyangizni chaqiramiz







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




@router.message(AdminChannelsState.adding_channel)
async def process_channel_input(message: Message, state: FSMContext, session: AsyncSession):
    input_text = message.text.strip()
    
    try:
        chat = await message.bot.get_chat(input_text)
        
        if chat.type not in ["channel", "supergroup"]:
            return await message.answer("❌ Bu kanal yoki superguruh emas.")
            
        # Repositorydagi metodingiz nomi to'g'ri ekanligini tekshiring
        existing_channel = await ChannelRepository.get_channel_by_id(session, chat.id)
        if existing_channel:
            return await message.answer("❌ Bu kanal allaqachon tizimda mavjud.")
        
        invite_link = chat.invite_link or f"https://t.me/{chat.username}" if chat.username else "N/A"
        
        await state.update_data(
            channel_id=chat.id,
            title=chat.title,
            url=invite_link
        )
        
        # 'kb' emas, 'builder' ishlatilishi kerak
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="✅ Tasdiqlayman", callback_data="confirm_add_channel"))
        builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_admin_channels"))
        
        await message.answer(
            f"🔎 Kanal topildi:\n\n"
            f"<b>Nomi:</b> {chat.title}\n"
            f"<b>ID:</b> {chat.id}\n\n"
            "Ushbu kanalni tizimga qo'shishni tasdiqlaysizmi?", 
            reply_markup=builder.as_markup(), # builder ishlatildi
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Kanal topishda xatolik: {e}")
        await message.answer("❌ Kanal topilmadi. Bot kanal admini ekanligiga va ID/username to‘g‘riligiga ishonch hosil qiling.")






# Tasdiqlash tugmasi bosilganda
@router.callback_query(F.data == "confirm_add_channel")
async def confirm_add(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_admin_channels"))
    try:
        # Repository orqali bazaga saqlash
        await ChannelRepository.add_channel(
            session, 
            channel_id=data['channel_id'], 
            title=data['title'], 
            url=data['url']
        )
        await callback.message.edit_text("✅ Kanal muvaffaqiyatli qo'shildi va kesh tozalandi!")
    except Exception as e:
        logger.error(f"Bazaga saqlash xatosi: {e}")
        await callback.message.edit_text("❌ Bazaga saqlashda xatolik yuz berdi.")
        
    await state.clear()


