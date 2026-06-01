import logging
from aiogram import Router, F, types
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext, Any
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
    action: str
    channel_id: int
    page: int

# ========================================================================
# 📢 1. KANALLAR RO'YXATI (MAIN HANDLER)
# ========================================================================
@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery, state: FSMContext, session: Any):
    # 🔥 FIX: To'g'ridan-to'g'ri SafeSession'ni ishlatamiz (Lazy Loading o'zi ochadi)
    await _execute_channel_listing(callback, state, session, page=1)

# ========================================================================
# 📄 2. PAGINATSIYA HANDLERI
# ========================================================================
@router.callback_query(ChannelsPageCallback.filter())
async def process_channels_page(callback: CallbackQuery, callback_data: ChannelsPageCallback, state: FSMContext, session: Any):
    await _execute_channel_listing(callback, state, session, page=callback_data.page)

# ========================================================================
# ⚙️ 3. RO'YXATNI GENERATSIYA QILISH CORE FUNKSIYASI
# ========================================================================
async def _execute_channel_listing(callback: CallbackQuery, state: FSMContext, session: Any, page: int = 1):
    try:
        await callback.answer("📋 Kanallar ro'yxati yuklanmoqda...")
        
        activ_channels = await ChannelRepository.get_all_active_channels(session)
        channels = await ChannelRepository.get_all_channels(session)
        
        if not channels:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
            return await callback.message.edit_text(
                "📭 Tizimda hozircha birorta ham kanal mavjud emas.", 
                reply_markup=builder.as_markup()
            )
        
        PER_PAGE = 5
        total_channels = len(channels)
        total_pages = (total_channels + PER_PAGE - 1) // PER_PAGE
        
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE
        page_channels = channels[start_idx:end_idx]
        
        builder = InlineKeyboardBuilder()
        
        for ch in page_channels:
            status = "🟢" if ch.get("is_active", True) else "🔴" 
            text = f"{status} {ch['title']}"
            
            builder.row(
                types.InlineKeyboardButton(
                    text=text,
                    callback_data=ChannelDetailCallback(channel_id=int(ch["channel_id"]), page=page).pack()
                )
            )
        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(types.InlineKeyboardButton(text="⬅️ Oldingi", callback_data=ChannelsPageCallback(page=page - 1).pack()))
        else:
            nav_buttons.append(types.InlineKeyboardButton(text="🔹", callback_data="noop"))
            
        nav_buttons.append(types.InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
        
        if page < total_pages:
            nav_buttons.append(types.InlineKeyboardButton(text="Keyingi ➡️", callback_data=ChannelsPageCallback(page=page + 1).pack()))
        else:
            nav_buttons.append(types.InlineKeyboardButton(text="🔹", callback_data="noop"))
            
        builder.row(*nav_buttons)
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
        
        text = (
            f"📋 <b>TIZIMDAGI KANALLAR</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Jami kanallar: <b>{total_channels}</b> ta\n"
            f"Faol kanallar: <b>{len(activ_channels)}</b> ta\n\n"
            f"👇 <i>Kanal sozlamalarini ko'rish uchun uning ustiga bosing:</i>"
        )
        
        try:
            await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=builder.as_markup())
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e): raise e
            
    except Exception as e:
        logger.error(f"Kanal ro'yxatini olishda xatolik: {e}")

# ========================================================================
# 🔍 4. KANAL BAFASIL MA'LUMOTI (DETAIL)
# ========================================================================
@router.callback_query(ChannelDetailCallback.filter())
async def view_channel_detail(callback: CallbackQuery, callback_data: ChannelDetailCallback, state: FSMContext, session: Any):
    await callback.answer("⏳ Yuklanmoqda...")
    channel = await ChannelRepository.get_channel_by_id(session, callback_data.channel_id)
    
    if not channel:
        return await callback.message.edit_text(
            "❌ Kanal topilmadi yoki u tizimdan o'chirilgan.",
            reply_markup=InlineKeyboardBuilder().row(
                types.InlineKeyboardButton(text="🔙 Ro'yxatga qaytish", callback_data=ChannelsPageCallback(page=callback_data.page).pack())
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
    builder.row(types.InlineKeyboardButton(text="🗑 Kanalni o'chirish", callback_data=ChannelDeleteCallback(action="ask", channel_id=channel['channel_id'], page=callback_data.page).pack()))
    builder.row(types.InlineKeyboardButton(text="🔙 Ro'yxatga qaytish", callback_data=ChannelsPageCallback(page=callback_data.page).pack()))
    
    await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=builder.as_markup(), disable_web_page_preview=True)

# ========================================================================
# ⚠️ 5. O'CHIRISHNI TASDIQLASH SO'ROVI (UX CONFIRM)
# ========================================================================
@router.callback_query(ChannelDeleteCallback.filter(F.action == "ask"))
async def ask_delete_channel(callback: CallbackQuery, callback_data: ChannelDeleteCallback, state: FSMContext, session: Any):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🔴 Ha, o'chirilsin", callback_data=ChannelDeleteCallback(action="confirm", channel_id=callback_data.channel_id, page=callback_data.page).pack()),
        types.InlineKeyboardButton(text="🟢 Yo'q, bekor qilish", callback_data=ChannelDetailCallback(channel_id=callback_data.channel_id, page=callback_data.page).pack())
    )
    await callback.message.edit_text(
        text="⚠️ <b>DIQQAT: KANAL TIZIMDAN O'CHIRILMOQDA</b>\n\nBu amalni ortga qaytarib bo'lmaydi!",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )

# ========================================================================
# 🚀 6. HAQIQIY O'CHIRISH AMALIYOTI (EXECUTE)
# ========================================================================
@router.callback_query(ChannelDeleteCallback.filter(F.action == "confirm"))
async def execute_delete_channel(callback: CallbackQuery, callback_data: ChannelDeleteCallback, state: FSMContext, session: Any):
    builder_back = InlineKeyboardBuilder()
    builder_back.row(types.InlineKeyboardButton(text="🔙 Kanallar ro'yxatiga qaytish", callback_data=ChannelsPageCallback(page=callback_data.page).pack()))
    
    await callback.answer("⏳ O'chirish jarayoni bajarilmoqda...")
    
    # 🔥 FIX: Biz ayni shu yerda SafeSession proxy'ni Repository'ga beryapmiz. 
    # U baza operatsiyasini bajarib, keshni faqatgina Middleware COMMIT bo'lgandan keyin o'chiradi.
    success = await ChannelRepository.delete_channel_by_id(session, callback_data.channel_id)
    
    if success:
        text = "🗑 <b>Kanal muvaffaqiyatli o'chirildi!</b>\n\nBarcha bog'liqliklar tozalab tashlandi. ✅"
    else:
        text = "❌ Xatolik: Kanal topilmadi yoki u allaqachon bazadan o'chirib yuborilgan."

    try:
        await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=builder_back.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await callback.message.answer(text=text, parse_mode="HTML", reply_markup=builder_back.as_markup())

# ========================================================================
# 💤 7. BO'SH CALLBACK (NOOP)
# ========================================================================
@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()