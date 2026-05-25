
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





#=============================list_channels==============================#
#========================================================================#
@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery, state: FSMContext, **kwargs):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    
    actual_session = getattr(safe_session, "_session", None)

    if actual_session is not None:
        # Tirik sessiya bo'lsa, to'g'ridan-to'g'ri chaqiramiz
        await _execute_channel_listing(callback, state, actual_session)
        return  # Blokdan tashqarida return qilish xavfsiz
        
    elif session_pool is not None:
        # Yangi sessiya ochamiz
        async with session_pool() as new_session:
            # Funksiya await bo'lib to'liq tugashini kutamiz, keyin context yopiladi
            await _execute_channel_listing(callback, state, new_session)
        return
        
    else:
        # callback.message.answer o'rniga callback.answer ishlatish yoki 
        # edit_text qilish yaxshiroq, chunki bu callback handler
        await callback.answer("❌ Tizim xatosi: Ma'lumotlar bazasiga ulanib bo'lmadi.", show_alert=True)








#========================_execute_channel_listing========================#
#========================================================================#
async def _execute_channel_listing(
    callback: CallbackQuery, 
    state: FSMContext, 
    session: AsyncSession, 
    page: int = 1
):
    try:
        await callback.answer()
        channels = await ChannelRepository.get_all_channels(session)
        
        # 1-Holat: Kanallar mavjud bo'lmasa
        if not channels:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
            return await callback.message.edit_text(
                "📭 Hozircha tizimda birorta ham kanal qo'shilmagan.", 
                reply_markup=builder.as_markup()
            )
        
        # Pagination sozlamalari
        PER_PAGE = 5
        total_channels = len(channels)
        total_pages = (total_channels + PER_PAGE - 1) // PER_PAGE
        
        # Sahifa chegaradan chiqib ketmasligi tekshiruvi
        page = max(1, min(page, total_pages))
        
        # Joriy sahifaga tegishli kanallarni kesib olish (Slice)
        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE
        page_channels = channels[start_idx:end_idx]
        
        # Tugmalarni yig'ish
        builder = InlineKeyboardBuilder()
        
        # 1. Kanallar tugmalari (Har biri alohida qatorda)
        for channel in page_channels:
            builder.row(
                types.InlineKeyboardButton(
                    text=f"📢 {channel.title}",
                    callback_data=ChannelDetailCallback(channel_id=channel.channel_id, page=page).pack()
                )
            )
        
        # 2. Navigatsiya tugmalari (Siz yuborgan rasmdagidek bitta qatorda 3 ta tugma)
        nav_buttons = []
        
        # Oldingi sahifa tugmasi
        if page > 1:
            nav_buttons.append(
                types.InlineKeyboardButton(
                    text="⬅️ Oldingi", 
                    callback_data=ChannelsPageCallback(page=page - 1).pack()
                )
            )
        else:
            nav_buttons.append(types.InlineKeyboardButton(text="❌", callback_data="noop"))
            
        # Joriy sahifa ko'rsatkichi
        nav_buttons.append(
            types.InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}", 
                callback_data="noop"
            )
        )
        
        # Keyingi sahifa tugmasi
        if page < total_pages:
            nav_buttons.append(
                types.InlineKeyboardButton(
                    text="Keyingi ➡️", 
                    callback_data=ChannelsPageCallback(page=page + 1).pack()
                )
            )
        else:
            nav_buttons.append(types.InlineKeyboardButton(text="❌", callback_data="noop"))
            
        builder.row(*nav_buttons)
        
        # 3. Eng pastdagi doimiy "Orqaga" tugmasi
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
        
        text = (
            f"📋 <b>TIZIMDAGI KANALLAR</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Jami kanallar: <b>{total_channels}</b> ta\n\n"
            f"Kanal haqida batafsil ma'lumot olish va uni o'chirish uchun ustiga bosing:"
        )
        
        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Kanal ro'yxatini olishda xatolik: {e}")
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
        await callback.message.edit_text(
            "❌ Tizim xatosi: Ma'lumotlarni yuklashda xatolik yuz berdi.",
            reply_markup=builder.as_markup()
        )







#=========================process_channels_page==========================#
#========================================================================#
@router.callback_query(ChannelsPageCallback.filter())
async def process_channels_page(callback: CallbackQuery, callback_data: ChannelsPageCallback, state: FSMContext, **kwargs):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    actual_session = getattr(safe_session, "_session", None)

    if actual_session is not None:
        await _execute_channel_listing(callback, state, actual_session, page=callback_data.page)
    elif session_pool is not None:
        async with session_pool() as new_session:
            await _execute_channel_listing(callback, state, new_session, page=callback_data.page)






#=========================view_channel_detail============================#
#========================================================================#
@router.callback_query(ChannelDetailCallback.filter())
async def view_channel_detail(callback: CallbackQuery, callback_data: ChannelDetailCallback, state: FSMContext, **kwargs):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    actual_session = getattr(safe_session, "_session", None)
    
    async def _show_detail(session: AsyncSession):
        await callback.answer()
        channel = await ChannelRepository.get_channel_by_id(session, callback_data.channel_id)
        
        if not channel:
            return await callback.message.edit_text(
                "❌ Kanal topilmadi yoki u allaqachon o'chirilgan.",
                reply_markup=InlineKeyboardBuilder().row(
                    types.InlineKeyboardButton(text="🔙 Ro'yxatga qaytish", callback_data=ChannelsPageCallback(page=callback_data.page).pack())
                ).as_markup()
            )
            
        text = (
            f"📢 <b>KANAL MA'LUMOTLARI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>📌 Nomi:</b> {channel.title}\n"
            f"<b>🆔 ID:</b> <code>{channel.channel_id}</code>\n"
            f"<b>🔗 Havola:</b> <a href='{channel.url}'>Ochish</a>\n\n"
            f"<i>Ushbu kanal boshqaruv panelidasiz.</i>"
        )
        
        builder = InlineKeyboardBuilder()
        # Kelajakda kanalni o'chirish tugmasini mana shu yerga qo'shishingiz mumkin
        builder.row(types.InlineKeyboardButton(text="🗑 Kanalni o'chirish", callback_data=f"delete_channel_{channel.channel_id}"))
        
        # 💡 PRO UX: Ortga bosganda foydalanuvchi adashib ketmasligi uchun aynan o'zi turgan sahifaga qaytaramiz!
        builder.row(
            types.InlineKeyboardButton(
                text="🔙 Ro'yxatga qaytish", 
                callback_data=ChannelsPageCallback(page=callback_data.page).pack()
            )
        )
        
        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True
        )

    # Tizimli sessiya boshqaruvi integration
    if actual_session is not None:
        await _show_detail(actual_session)
    elif session_pool is not None:
        async with session_pool() as new_session:
            await _show_detail(new_session)




#===========================noop_callback================================#
#========================================================================#
@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()