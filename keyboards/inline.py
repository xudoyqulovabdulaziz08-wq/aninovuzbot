from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from config import config

CREATOR_ID = config.CREATOR_ID


# Search bo'limidagi inline klaviaturani yaratish funksiyasi
def search_inline_kb(is_vip: bool = False) -> types.InlineKeyboardMarkup:
    """
    is_vip: Handlerdan keladigan foydalanuvchi statusi.
    """
    builder = InlineKeyboardBuilder()

    # 1. Faqat VIP foydalanuvchilar uchun Tezkor qidiruv tugmasi
    if is_vip or config.CREATOR_ID == config.CREATOR_ID:  # Creator ham VIP imkoniyatlarga ega bo'lishi kerak:
        builder.row(
            types.InlineKeyboardButton(
                text="⚡️ Tezkor qidiruv (VIP)",
                switch_inline_query_current_chat="" # Bo'sh joy bilan inline rejimni ochadi
            )
        )
    
    # 2. Oddiy qidiruv usullari (Hamma uchun)
    builder.row(
        types.InlineKeyboardButton(text="🔍 Nomi bo'yicha", callback_data="search_by_name"),
        types.InlineKeyboardButton(text="🆔 ID bo'yicha", callback_data="search_by_id")
    )

    # 3. Janr va Sayt
    builder.row(
        types.InlineKeyboardButton(text="🎭 Janr bo'yicha", callback_data="search_by_genre"),
        types.InlineKeyboardButton(text="🔗 Rasmiy sayt", url="https://aninovuz.uz")
    )

    return builder.as_markup()






def admin_panel_kb(is_admin : bool) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Faqat admin yoki creator bo'lsa tugmalarni qo'shish
    if is_admin or CREATOR_ID == config.CREATOR_ID:
        # Har bir row alohida qator yaratadi
        builder.row(
            types.InlineKeyboardButton(text="🎛️ Anime boshqaruv paneli", callback_data="admin_anime_panel")
            ) # Katta tugma
        builder.row(
            types.InlineKeyboardButton(text="📢 Kanallar", callback_data="admin_channels"),
            types.InlineKeyboardButton(text="📣 Reklama", callback_data="admin_advertisement")
        )
        builder.row(
            types.InlineKeyboardButton(text="📊 Statistika", callback_data="admin_statistics"),
            types.InlineKeyboardButton(text="💎 VIP", callback_data="admin_vip_panel")
        )
        builder.row(
            types.InlineKeyboardButton(text="📃 Murojaatlar", callback_data="admin_reports"),
            types.InlineKeyboardButton(text="👥 Users control", callback_data="admin_users_panel")
                    
        ) # Katta tugma
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