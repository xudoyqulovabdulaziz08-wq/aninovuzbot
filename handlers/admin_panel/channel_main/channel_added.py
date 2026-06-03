import logging
import copy
from typing import Any, Dict
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from database.repository import ChannelRepository

router = Router()
logger = logging.getLogger(__name__)

# Tizim yaratuvchisi ID'si (Agar kerak bo'lsa tekshirish uchun)
CREATOR_ID = getattr(config, 'CREATOR_ID', None)


class AdminChannelsState(StatesGroup):
    adding_channel = State()


# ============================ ADMIN CHANNELS MENU ============================ #
# ============================================================================= #
@router.callback_query(F.data == "add_channel")
async def add_channel(callback: CallbackQuery, state: FSMContext):
    # 1. Oldingi holatni har ehtimolga qarshi tozalab, yangisini o'rnatamiz
    await state.clear()
    await state.set_state(AdminChannelsState.adding_channel)
    
    # 2. Chiroyli dizayn va ramkali matn
    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "      <b>KANAL QO'SHISH</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "🤖 Tizimga majburiy obuna kanalini qo'shish uchun:\n\n"
        "📍 <b>Shartlar:</b>\n"
        "• Bot ushbu kanalda <b>Admin</b> bo'lishi shart.\n"
        "• Xabar yuborish (Post) huquqi yoqilgan bo'lishi kerak.\n\n"
        "📝 Kanal <b>ID</b>sini yoki <b>username</b>ini yuboring:\n"
        "<i>(Misol: @username yoki -100xxxxxxxxxx)</i>"
    )
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
    
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Admin kanallar UI xatosi: {e}")
            
    await callback.answer("⛩ Kanal qo'shish tartibi faollashdi.")


# ========================== PROCESS CHANNEL INPUT ========================== #
# =========================================================================== #
@router.message(AdminChannelsState.adding_channel)
async def process_channel_input(message: Message, state: FSMContext, **data):
    safe_session = data.get("session")
    session_pool = data.get("session_pool")
    
    # SafeSession obyekti ichidan haqiqiy jonli ulanishni tekshiramiz
    actual_session = getattr(safe_session, "_session", None)

    if actual_session is not None:
        # Jonli middleware sessiyasi mavjud bo'lsa
        return await _execute_channel_adding(message, state, actual_session)
    elif session_pool is not None:
        # Kesh rejimi faol bo'lsa (Sessiya yo'q), yangi sessiya hovuzidan ochamiz
        async with session_pool() as new_session:
            return await _execute_channel_adding(message, state, new_session)
    else:
        # Kritik xatolik yuz bersa (Infratuzilma himoyasi)
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="⛩ Boshqaruv paneli", callback_data="admin_channels"))
        await state.clear()  # Deadlock bo'lmasligi uchun holatni yopamiz
        return await message.answer(
            "❌ <b>Tizim xatosi:</b> Ma'lumotlar bazasiga ulanish hovuzi (Session Pool) topilmadi.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )


# ========================= _EXECUTE CHANNEL ADDING ========================= #
# =========================================================================== #
async def _execute_channel_adding(message: Message, state: FSMContext, session: AsyncSession):
    input_text = message.text.strip()
    
    # Har doim xavfsiz qaytishni ta'minlovchi tugma arxitekturasi
    builder_back = InlineKeyboardBuilder()
    builder_back.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels_clear_state"))
    back_markup = builder_back.as_markup()
    
    try:
        # Telegram API orqali kanal ma'lumotlarini tekshiramiz
        chat = await message.bot.get_chat(input_text)
        
        # 1-Ssenariy: Chat topildi, lekin u kanal yoki superguruh emas
        if chat.type not in ["channel", "supergroup"]:
            return await message.answer(
                "╔═════════ ⛩ ═════════╗\n"
                "      <b>NOTO'G'RI TIP</b>\n"
                "╚═════════ ⛩ ═════════╝\n\n"
                "❌ Kiritilgan havola kanal yoki superguruhga tegishli emas!\n"
                "Iltimos, faqat ommaviy/shaxsiy kanallarni kiriting.", 
                reply_markup=back_markup,
                parse_mode="HTML"
            )
            
        # 2-Ssenariy: Kanal allaqachon DB reposida mavjud bo'lsa
        existing_channel = await ChannelRepository.get_channel_by_id(session, chat.id)
        if existing_channel:
            return await message.answer(
                "╔═════════ ⛩ ═════════╗\n"
                "     <b>MAVJUD KANAL</b>\n"
                "╚═════════ ⛩ ═════════╝\n\n"
                "❌ Ushbu kanal allaqachon tizim ma'lumotlar bazasida mavjud!\n"
                "Dublikat kanallarni qo'shish taqiqlanadi.", 
                reply_markup=back_markup,
                parse_mode="HTML"
            )
        
        # Takroriy tekshiruv havolasini tayyorlash
        invite_link = chat.invite_link or f"https://t.me/{chat.username}" if chat.username else "N/A"
        
        # Tasdiqlash bosqichi uchun ma'lumotlarni FSM keshiga yozamiz
        await state.update_data(
            channel_id=chat.id,
            title=chat.title,
            url=invite_link
        )
        
        # Muvaffaqiyatli topilgan kanalning estetik kartasi
        builder_confirm = InlineKeyboardBuilder()
        builder_confirm.row(types.InlineKeyboardButton(text="✅ Tasdiqlayman", callback_data="confirm_add_channel"))
        builder_confirm.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels_clear_state"))
        
        text_success = (
            "╔═════════ ⛩ ═════════╗\n"
            "      <b>KANAL TOPILDI</b>\n"
            "╚═════════ ⛩ ═════════╝\n\n"
            f"📡 <b>Nomi:</b> <code>{chat.title}</code>\n"
            f"🆔 <b>ID:</b> <code>{chat.id}</code>\n"
            f"🔗 <b>Havola:</b> {invite_link}\n\n"
            "❔ Ushbu kanalni majburiy obunalar ro'yxatiga qo'shishni tasdiqlaysizmi?"
        )
        
        await message.answer(
            text_success, 
            reply_markup=builder_confirm.as_markup(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"❌ Telegram API orqali kanal topishda xatolik: {e}")
        await message.answer(
            "╔═════════ ⛩ ═════════╗\n"
            "     <b>API XATOLIK</b>\n"
            "╚═════════ ⛩ ═════════╝\n\n"
            "❌ Kanal topilmadi yoki bot admin emas!\n\n"
            "<b>Mumkin bo'lgan sabablar:</b>\n"
            "1. Botni ushbu kanalga qo'shmagansiz.\n"
            "2. Botga adminlik huquqini bermagansiz.\n"
            "3. ID yoki Username yozishda xatolikka yo'l qo'ydingiz.",
            reply_markup=back_markup,
            parse_mode="HTML"
        )


# ============================= CONFIRM ADD ============================= #
# ======================================================================= #
# ============================= CONFIRM ADD (TUZATILDI) ============================= #
# =================================================================================== #
@router.callback_query(F.data == "confirm_add_channel")
async def confirm_add(callback: CallbackQuery, state: FSMContext, **kwargs):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    channel_data = await state.get_data()
    
    # SafeSession proxy ichidan jonli sessiyani ajratamiz
    actual_session = getattr(safe_session, "_session", None)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Kanallar ro'yxati", callback_data="admin_channels"))
    back_markup = builder.as_markup()
    
    try:
        if not channel_data or 'channel_id' not in channel_data:
            raise ValueError("Kesh ma'lumotlari bo'sh yoki muddati eskirgan.")

        # ID son ekanligini va BigInteger kuta olishini ta'minlash uchun int() ga o'giramiz
        target_channel_id = int(channel_data['channel_id'])

        if actual_session is not None:
            # 1-Ssenariy: Middleware sessiyasi mavjud.
            # DIQQAT: Repository ichida session.commit() chaqirilmasligi kerak!
            # Faqat session.add() va session.flush() yetarli. Commit'ni middleware o'zi qiladi.
            await ChannelRepository.add_channel(
                session=actual_session, 
                channel_id=target_channel_id, 
                title=channel_data['title'], 
                url=channel_data['url']
            )
            # Agarda repository ichida commit bo'lmasa, o'zgarishlar middleware orqali yoziladi.
            
        elif session_pool is not None:
            # 2-Ssenariy: Middleware'dan tashqarida (Kesh rejimi)
            async with session_pool() as new_session:
                await ChannelRepository.add_channel(
                    session=new_session, 
                    channel_id=target_channel_id, 
                    title=channel_data['title'], 
                    url=channel_data['url']
                )
                # Alvohida ochilgan sessiyada qo'lda commit qilamiz
                await new_session.commit()
        else:
            raise RuntimeError("Infratuzilmada ulanishlar hovuzi (Session Pool) aniqlanmadi.")

        # Muvaffaqiyatli xabar
        await callback.message.edit_text(
            "╔═════════ ⛩ ═════════╗\n"
            "     <b>MUVAFFAQIYAT</b>\n"
            "╚═════════ ⛩ ═════════╝\n\n"
            f"✅ <b>Kanal muvaffaqiyatli saqlandi!</b>\n"
            f"📡 <b>Kanal:</b> {channel_data['title']}\n\n"
            "⚙ <i>Infratuzilma yangilandi: Kesh invalidatsiya qilindi, "
            "tarqatish workerlari yangi obunani qabul qilishga tayyor.</i>", 
            reply_markup=back_markup,
            parse_mode="HTML"
        )
        
    except Exception as e:
        # Xatoni logga to'liq traceback bilan yozamiz, shunda aniq sababi ko'rinadi
        logger.error(f"❌ KANAL QO'SHISHDA TRANZAKSIYA QULADI: {e}", exc_info=True)
        
        await callback.message.edit_text(
            "╔═════════ ⛩ ═════════╗\n"
            "    <b>TRANZAKSIYA XATOSI</b>\n"
            "╚═════════ ⛩ ═════════╝\n\n"
            f"❌ Ma'lumotlarni bazaga yozishda ichki xatolik yuz berdi.\n\n"
            f"⚠️ <b>Xatolik turi:</b> <code>{type(e).__name__}</code>\n"
            "<i>Tizim jurnallarini (logs) tekshiring. Katta ehtimol bilan ChannelRepository ichidagi commit yoki OutboxEvent hashi to'qnashmoqda.</i>",
            reply_markup=back_markup,
            parse_mode="HTML"
        )
        
    finally:
        # FSM holatni har qanday vaziyatda tozalaymiz
        await state.clear()

# ======================== EXTRA UTILITY HANDLER ======================== #
# FSM holatini xavfsiz tozalab keyin orqaga qaytaradigan maxsus tugma handler'i
@router.callback_query(F.data == "admin_channels_clear_state")
async def admin_channels_clear_state(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Holatni (State) to'liq yopamiz, foydalanuvchi "asir" bo'lib qolmaydi
    # Bu yerda admin_channels menyusi chaqiriladi (Sizning loyihadagi asosiy tugmalar handleringizga mos)
    # Masalan, admin_channels menyusini ko'rsatish funksiyasini trigger qilamiz:
    await callback.answer("⛩ Holat tozalandi.")
    # Menyu matnini loyihangizdagi admin_channels mantiqiga o'tkazib yuboramiz
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel"))
    await callback.message.edit_text(
        "╔═════════ ⛩ ═════════╗\n"
        "   <b>KANALLARNI BOSHQARISH</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Majburiy obuna tizimi sozlamalari panelidasiz.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )