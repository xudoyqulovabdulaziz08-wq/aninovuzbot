import logging
from aiogram import Router, F, types
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from sqlalchemy.ext.asyncio import AsyncSession
from database.repository import ChannelRepository

logger = logging.getLogger("AdminChannels")
router = Router()

# ========================================================================
# 🛠 STRUKTURALASHGAN CALLBACK DATA KLASSlari
# ========================================================================
class ChannelsPageCallback(CallbackData, prefix="ch_page"):
    page: int

class ChannelDetailCallback(CallbackData, prefix="ch_detail"):
    channel_id: int
    page: int

class ChannelDeleteCallback(CallbackData, prefix="ch_del"):
    action: str  # "ask" yoki "confirm"
    channel_id: int
    page: int


# ========================================================================
# 📢 1. KANALLAR RO'YXATI (MAIN HANDLER)
# ========================================================================
@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery, state: FSMContext, **kwargs):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    actual_session = getattr(safe_session, "_session", None)

    if actual_session is not None:
        await _execute_channel_listing(callback, state, actual_session, page=1)
        return
    elif session_pool is not None:
        async with session_pool() as new_session:
            await _execute_channel_listing(callback, state, new_session, page=1)
        return
    else:
        await callback.answer("❌ Tizim xatosi: Ma'lumotlar bazasiga ulanib bo'lmadi.", show_alert=True)


# ========================================================================
# 📄 2. PAGINATSIYA HANDLERI
# ========================================================================
@router.callback_query(ChannelsPageCallback.filter())
async def process_channels_page(
    callback: CallbackQuery, 
    callback_data: ChannelsPageCallback, 
    state: FSMContext, 
    **kwargs
):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    actual_session = getattr(safe_session, "_session", None)

    if actual_session is not None:
        await _execute_channel_listing(callback, state, actual_session, page=callback_data.page)
    elif session_pool is not None:
        async with session_pool() as new_session:
            await _execute_channel_listing(callback, state, new_session, page=callback_data.page)


# ========================================================================
# ⚙️ 3. RO'YXATNI GENERATSIYA QILISH VA CHIQARISH CORE FUNKSIYASI
# ========================================================================
async def _execute_channel_listing(
    callback: CallbackQuery, 
    state: FSMContext, 
    session: AsyncSession, 
    page: int = 1
):
    try:
        await callback.answer("📋 Kanallar ro'yxati yuklanmoqda...")
        
        # Ma'lumotlarni bazadan dict formatida olish
        activ_channels = await ChannelRepository.get_all_active_channels(session)
        channels = await ChannelRepository.get_all_channels(session)
        
        # Kanallar mavjud bo'lmagan holat
        if not channels:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
            return await callback.message.edit_text(
                "📭 Tizimda hozircha birorta ham kanal mavjud emas.", 
                reply_markup=builder.as_markup()
            )
        
        # Pagination hisob-kitoblari
        PER_PAGE = 5
        total_channels = len(channels)
        total_pages = (total_channels + PER_PAGE - 1) // PER_PAGE
        
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE
        page_channels = channels[start_idx:end_idx]
        
        builder = InlineKeyboardBuilder()
        
        # Kanallarni tugma qilib ro'yxatga terish
        for ch in page_channels:
            status = "🟢" if ch.get("is_active", True) else "🔴" 
            text = f"{status} {ch['title']}"
            
            builder.row(
                types.InlineKeyboardButton(
                    text=text,
                    callback_data=ChannelDetailCallback(
                        channel_id=int(ch["channel_id"]), 
                        page=page
                    ).pack()
                )
            )
        
        # Navigatsiya boshqaruvi
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                types.InlineKeyboardButton(
                    text="⬅️ Oldingi", 
                    callback_data=ChannelsPageCallback(page=page - 1).pack()
                )
            )
        else:
            nav_buttons.append(types.InlineKeyboardButton(text="🔹", callback_data="noop"))
            
        nav_buttons.append(
            types.InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}", 
                callback_data="noop"
            )
        )
        
        if page < total_pages:
            nav_buttons.append(
                types.InlineKeyboardButton(
                    text="Keyingi ➡️", 
                    callback_data=ChannelsPageCallback(page=page + 1).pack()
                )
            )
        else:
            nav_buttons.append(types.InlineKeyboardButton(text="🔹", callback_data="noop"))
            
        builder.row(*nav_buttons)
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
        
        text = (
            f"📋 <b>TIZIMDAGI KANALLAR</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Jami kanallar: <b>{total_channels}</b> ta\n"
            f"Faol kanallar: <b>{len(activ_channels)}</b> ta\n\n"
            f"👇 <i>Kanal sozlamalarini ko'rish va boshqarish uchun kerakli kanal ustiga bosing:</i>"
        )
        
        try:
            await callback.message.edit_text(
                text=text,
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise e
        
    except Exception as e:
        logger.error(f"Kanal ro'yxatini olishda xatolik: {e}", exc_info=True)
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
        try:
            await callback.message.edit_text(
                "❌ Tizim xatosi: Ma'lumotlarni yuklash muvaffaqiyatsiz tugadi.",
                reply_markup=builder.as_markup()
            )
        except Exception:
            pass


# ========================================================================
# 🔍 4. KANAL BAFASIL MA'LUMOTI (DETAIL)
# ========================================================================
@router.callback_query(ChannelDetailCallback.filter())
async def view_channel_detail(
    callback: CallbackQuery, 
    callback_data: ChannelDetailCallback, 
    state: FSMContext, 
    **kwargs
):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    actual_session = getattr(safe_session, "_session", None)
    
    async def _show_detail(session: AsyncSession):
        await callback.answer("⏳ Yuklanmoqda...")
        channel = await ChannelRepository.get_channel_by_id(session, callback_data.channel_id)
        
        if not channel:
            return await callback.message.edit_text(
                "❌ Kanal topilmadi yoki u tizimdan o'chirilgan.",
                reply_markup=InlineKeyboardBuilder().row(
                    types.InlineKeyboardButton(
                        text="🔙 Ro'yxatga qaytish", 
                        callback_data=ChannelsPageCallback(page=callback_data.page).pack()
                    )
                ).as_markup()
            )
        
        status_text = "🟢 Faol (Majburiy obuna ochiq)" if channel.get("is_active", True) else "🔴 Noaktiv (Vaqtincha o'chirilgan)"
        text = (
            f"📢 <b>KANAL MA'LUMOTLARI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>📌 Nomi:</b> {channel['title']}\n"
            f"<b>🆔 ID:</b> <code>{channel['channel_id']}</code>\n"
            f"<b>⚙️ Holati:</b> {status_text}\n"
            f"<b>🔗 Havola:</b> <a href='{channel['url']}'>Kanalga o'tish</a>\n\n"
            f"<i>💡 Ushbu kanalni o'chirish yoki orqaga qaytishingiz mumkin.</i>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🗑 Kanalni o'chirish", 
                callback_data=ChannelDeleteCallback(
                    action="ask", 
                    channel_id=channel['channel_id'], 
                    page=callback_data.page
                ).pack()
            )
        )
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

    if actual_session is not None:
        await _show_detail(actual_session)
    elif session_pool is not None:
        async with session_pool() as new_session:
            await _show_detail(new_session)


# ========================================================================
# ⚠️ 5. O'CHIRISHNI TASDIQLASH SO'ROVI (UX CONFIRM)
# ========================================================================
@router.callback_query(ChannelDeleteCallback.filter(F.action == "ask"))
async def ask_delete_channel(
    callback: CallbackQuery, 
    callback_data: ChannelDeleteCallback, 
    state: FSMContext, 
    **kwargs
):
    await callback.answer("⚠️ Diqqat! Tasdiqlash talab etiladi.")
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🔴 Ha, o'chirilsin", 
            callback_data=ChannelDeleteCallback(
                action="confirm", 
                channel_id=callback_data.channel_id, 
                page=callback_data.page
            ).pack()
        ),
        types.InlineKeyboardButton(
            text="🟢 Yo'q, bekor qilish", 
            callback_data=ChannelDetailCallback(
                channel_id=callback_data.channel_id, 
                page=callback_data.page
            ).pack()
        )
    )
    
    await callback.message.edit_text(
        text="⚠️ <b>DIQQAT: KANAL TIZIMDAN O'CHIRILMOQDA</b>\n\n"
             "Ushbu kanalni ma'lumotlar bazasidan butunlay o'chirib tashlamoqchimisiz?\n"
             "<i>Bu amalni ortga qaytarib bo'lmaydi va foydalanuvchilar tekshiruvi keshdan tozalanadi!</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


# ========================================================================
# 🚀 6. HAQIQIY O'CHIRISH AMALIYOTI (EXECUTE)
# ========================================================================
@router.callback_query(ChannelDeleteCallback.filter(F.action == "confirm"))
async def execute_delete_channel(
    callback: CallbackQuery, 
    callback_data: ChannelDeleteCallback, 
    state: FSMContext, 
    **kwargs
):
    safe_session = kwargs.get("session")
    session_pool = kwargs.get("session_pool")
    actual_session = getattr(safe_session, "_session", None)
    
    # O'chirilgandan so'ng admin avval turgan sahifaga qaytadi
    builder_back = InlineKeyboardBuilder()
    builder_back.row(types.InlineKeyboardButton(
        text="🔙 Kanallar ro'yxatiga qaytish", 
        callback_data=ChannelsPageCallback(page=callback_data.page).pack()
    ))
    back_markup = builder_back.as_markup()

    async def _delete_logic(session: AsyncSession):
        await callback.answer("⏳ O'chirish jarayoni bajarilmoqda...")
        success = await ChannelRepository.delete_channel_by_id(session, callback_data.channel_id)
        
        if success:
            text = (
                "🗑 <b>Kanal muvaffaqiyatli o'chirildi!</b>\n\n"
                "Tizim ma'lumotlar bazasi va kesh xotirasidan barcha bog'liqliklar tozalab tashlandi. ✅"
            )
        else:
            text = "❌ Xatolik: Kanal topilmadi yoki u allaqachon bazadan o'chirib yuborilgan."

        try:
            await callback.message.edit_text(
                text=text,
                parse_mode="HTML",
                reply_markup=back_markup
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                await callback.message.answer(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=back_markup
                )

    if actual_session is not None:
        await _delete_logic(actual_session)
    elif session_pool is not None:
        async with session_pool() as new_session:
            await _delete_logic(new_session)


# ========================================================================
# 💤 7. BO'SH CALLBACK (NOOP)
# ========================================================================
@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()