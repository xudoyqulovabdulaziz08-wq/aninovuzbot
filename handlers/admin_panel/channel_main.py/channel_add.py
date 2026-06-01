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


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')



class AdminChannelsState(StatesGroup):
    adding_channel = State()
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






#==========================process_channel_input=========================#
#========================================================================#
@router.message(AdminChannelsState.adding_channel)
async def process_channel_input(message: Message, state: FSMContext, **data):
    safe_session = data.get("session")
    session_pool = data.get("session_pool")
    
    # Ichki haqiqiy ulanish bor yoki yo'qligini tekshiramiz
    # SafeSession klassingiz __dict__["_session"] ichida saqlaydi
    actual_session = getattr(safe_session, "_session", None)

    if actual_session is not None:
        # Agar middleware tasodifan tirik sessiya bergan bo'lsa, shundan foydalanamiz
        return await _execute_channel_adding(message, state, actual_session)
    elif session_pool is not None:
        # Kesh rejimi bo'lgani uchun sessiya yo'q, yangi sessiya ochamiz (Majburiy)
        async with session_pool() as new_session:
            return await _execute_channel_adding(message, state, new_session)
    else:
        # Agar na sessiya, na session_pool bo'lsa (Kritik xato)
        return await message.answer("❌ Tizim xatosi: Ma'lumotlar bazasiga ulanib bo'lmadi.")









#=========================_execute_channel_adding========================#
#========================================================================#
# Asosiy logikani alohida funksiyaga ajratdik (UX xavfsiz holatda)
async def _execute_channel_adding(message: Message, state: FSMContext, session: AsyncSession):
    input_text = message.text.strip()
    
    # 🛠 Har doim tayyor turadigan "Orqaga" tugmasi arxitekturasi
    builder_back = InlineKeyboardBuilder()
    builder_back.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
    back_markup = builder_back.as_markup()
    
    try:
        chat = await message.bot.get_chat(input_text)
        
        # 1-Holat: Kanal yoki guruh bo'lmasa
        if chat.type not in ["channel", "supergroup"]:
            return await message.answer(
                "❌ Bu kanal yoki superguruh emas. Iltimos, faqat kanal yoki guruh yuboring.", 
                reply_markup=back_markup
            )
            
        # 2-Holat: Kanal allaqachon bazada bor bo'lsa
        existing_channel = await ChannelRepository.get_channel_by_id(session, chat.id)
        if existing_channel:
            return await message.answer(
                "❌ Bu kanal allaqachon tizimda mavjud. Boshqa kanal kiritib ko'ring.", 
                reply_markup=back_markup
            )
        
        # Tasdiqlash jarayoni uchun ma'lumotlarni yig'ish
        invite_link = chat.invite_link or f"https://t.me/{chat.username}" if chat.username else "N/A"
        
        await state.update_data(
            channel_id=chat.id,
            title=chat.title,
            url=invite_link
        )
        
        # ✅ Kanal muvaffaqiyatli topilsa, Tasdiqlash / Bekor qilish tugmalari
        builder_confirm = InlineKeyboardBuilder()
        builder_confirm.row(types.InlineKeyboardButton(text="✅ Tasdiqlayman", callback_data="confirm_add_channel"))
        builder_confirm.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels")) # Bir xillik uchun admin_channels ga yo'naltirdik
        
        await message.answer(
            f"🔎 Kanal topildi:\n\n"
            f"<b>Nomi:</b> {chat.title}\n"
            f"<b>ID:</b> {chat.id}\n\n"
            "Ushbu kanalni tizimga qo'shishni tasdiqlaysizmi?", 
            reply_markup=builder_confirm.as_markup(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Kanal topishda xatolik: {e}")
        # 3-Holat: Telegram API'dan xatolik qaytsa (Kanal topilmasa)
        await message.answer(
            "❌ Kanal topilmadi. Bot kanal admini ekanligiga, unga xabar yuborish huquqi borligiga "
            "va ID/username to‘g‘riligiga ishonch hosil qiling.",
            reply_markup=back_markup
        )





#=============================confirm_add================================#
#========================================================================#
# Tasdiqlash tugmasi bosilganda

@router.callback_query(F.data == "confirm_add_channel")
async def confirm_add(callback: CallbackQuery, state: FSMContext, **kwargs):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    channel_data = await state.get_data()
    
    actual_session = getattr(safe_session, "_session", None)
    
    # Orqaga (Asosiy menyuga) qaytish tugmasi
    # NOTA: "back_to_menu" o'rniga loyihangizdagi asosiy menyu callback_data'sini yozing
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
    back_markup = builder.as_markup()
    
    try:
        # data bo'sh bo'lsa xatolik bermasligi uchun tekshiruv
        if not channel_data or 'channel_id' not in channel_data:
            raise ValueError("Kanal ma'lumotlari topilmadi yoki kesh muddati tugagan.")

        if actual_session is not None:
            # Tirik sessiya mavjud bo'lsa
            await ChannelRepository.add_channel(
                session=actual_session, 
                channel_id=channel_data['channel_id'], 
                title=channel_data['title'], 
                url=channel_data['url']
            )
        elif session_pool is not None:
            # Sessiya yo'q bo'lsa, yozish uchun yangisini ochamiz
            async with session_pool() as new_session:
                await ChannelRepository.add_channel(
                    session=new_session, 
                    channel_id=channel_data['channel_id'], 
                    title=channel_data['title'], 
                    url=channel_data['url']
                )
        else:
            raise RuntimeError("Database session pool topilmadi.")

        # ✅ Muvaffaqiyatli yakun va ortga qaytish tugmasi
        await callback.message.edit_text(
            "✅ Kanal muvaffaqiyatli qo'shildi va kesh tozalandi!", 
            reply_markup=back_markup
        )
        
    except Exception as e:
        logger.error(f"Bazaga saqlash xatosi: {e}")
        # ❌ Xatolik yuz berganda ham tugma chiqadi, foydalanuvchi qolib ketmaydi
        await callback.message.edit_text(
            "❌ Bazaga saqlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.",
            reply_markup=back_markup
        )
        
    finally:
        # Har qanday holatda ham (xato bo'lsa ham, bo'lmasa ham) stateni tozalaymiz
        await state.clear()


