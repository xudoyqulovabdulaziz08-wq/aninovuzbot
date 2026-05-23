from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.models import DBUser
from database.repository import UserRepository
from database.cache import cache_manager
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
        types.InlineKeyboardButton(text="🔗 Rasmiy sayt", url="https://aninovuz.uz")
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


# creator_id ni int qilib o'zgartirdik va ortiqcha 'user_status' ni olib tashladik
def creator_panel_kb(creator_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # config.CREATOR_ID ham int bo'lishi kerak
    if creator_id == config.CREATOR_ID:
        builder.row(
            types.InlineKeyboardButton(text="👑 Barcha adminlarni boshqarish", callback_data="creator_manage_admins")
        )
        builder.row(
            types.InlineKeyboardButton(text="📊 To'liq statistika", callback_data="creator_statistics"),
            types.InlineKeyboardButton(text="🗄️ Baza control", callback_data="creator_db_panel")
        )
    
    return builder.as_markup()



# keyboards/inline.py faylida:
def get_ranked_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🎬 Anime Reyting", callback_data="Anime_ranked"),
        types.InlineKeyboardButton(text="🏆 User Reyting", callback_data="User_ranked")
    )
    return builder.as_markup()


def vip_buy_kb(is_vip: bool) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if is_vip:
        builder.row(types.InlineKeyboardButton(text="💫 VIP muddatini uzaytirish", callback_data="activate_vip"))
    else:
        builder.row(types.InlineKeyboardButton(text="💎 100 ballga VIP sotib olish", callback_data="activate_vip"))
        
    builder.row(
        types.InlineKeyboardButton(text="🎁 Ball yig'ish", callback_data="get_ref_link"),
        types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet")
    )
    return builder.as_markup()

def cabinet_kb(is_vip: bool) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if is_vip:
        builder.row(types.InlineKeyboardButton(text="💫 VIP muddatini uzaytirish", callback_data="activate_vip"))
    else:
        builder.row(types.InlineKeyboardButton(text="💎 VIP sotib olish", callback_data="buy_vip_menu"))
        
    builder.row(
        types.InlineKeyboardButton(text="🔗 Taklif havola", callback_data="get_ref_link"),
        types.InlineKeyboardButton(text="🌐 Saytdagi profil", url="https://aninowuz.uz/profile")
    )
    return builder.as_markup()