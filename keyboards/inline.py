from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from config import config

CREATOR_ID = config.CREATOR_ID


# Search bo'limidagi inline klaviaturani yaratish funksiyasi
def search_inline_kb(is_privileged: bool = False) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # 1. Tezkor qidiruv (Faqat VIP/Creator uchun)
    if is_privileged:
        builder.row(
            types.InlineKeyboardButton(
                text="⚡️ Tezkor qidiruv (VIP)",
                switch_inline_query_current_chat=""
            )
        )
    
    # 2. Oddiy qidiruv usullari
    builder.row(
        types.InlineKeyboardButton(text="🔍 Nomi bo'yicha", callback_data="search_by_name"),
        types.InlineKeyboardButton(text="🆔 ID bo'yicha", callback_data="search_by_id")
    )

    # 3. Janr va Sayt
    builder.row(
        types.InlineKeyboardButton(text="🎭 Janr bo'yicha", callback_data="search_by_genre"),
        types.InlineKeyboardButton(text="🔗 Rasmiy sayt (Tez kunda)", url="https://aninovuz.uz")
    )

    return builder.as_markup()




def admin_panel_kb(user_id: int, user_status: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Faqat Creator yoki Admin bo'lsagina tugmalarni shakllantiramiz
    is_authorized = (user_id == config.CREATOR_ID or user_status == "admin")
    
    if is_authorized:
        # Asosiy katta tugma
        builder.row(types.InlineKeyboardButton(text="🎛️ Anime boshqaruv paneli", callback_data="admin_anime_panel"))
        
        # Ikkinchi qator
        builder.row(
            types.InlineKeyboardButton(text="📢 Kanallar", callback_data="admin_channels"),
            types.InlineKeyboardButton(text="📣 Reklama", callback_data="admin_advertisement")
        )
        
        # Uchinchi qator
        builder.row(
            types.InlineKeyboardButton(text="📊 Statistika", callback_data="admin_statistics"),
            types.InlineKeyboardButton(text="💎 VIP", callback_data="admin_vip_panel")
        )
        
        # To'rtinchi qator
        builder.row(
            types.InlineKeyboardButton(text="📃 Murojaatlar", callback_data="admin_reports"),
            types.InlineKeyboardButton(text="👥 Users control", callback_data="admin_users_panel")
        )
        
    return builder.as_markup()


def creator_panel_kb(Creator_ID: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if Creator_ID == config.CREATOR_ID:
        # Katta tugma alohida qatorda
        builder.row(
            types.InlineKeyboardButton(text="👑 Barcha adminlarni boshqarish", callback_data="creator_manage_admins")
        )
        # Kichikroq tugmalar yonma-yon bitta qatorda
        builder.row(
            types.InlineKeyboardButton(text="📊 To'liq statistika", callback_data="creator_statistics"),
            types.InlineKeyboardButton(text="🗄️ Baza control", callback_data="creator_db_panel")
        )
    
    return builder.as_markup()

