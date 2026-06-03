from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from urllib.parse import quote



from database.models import DBUser
from database.repository import UserRepository
from database.cache import cache_manager

from config import config


CREATOR_ID = config.CREATOR_ID



#===========================search_inline_kb=============================#
#========================================================================#
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





#============================admin_panel_kb==============================#
#========================================================================#
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
           
            types.InlineKeyboardButton(text="👥 Users control", callback_data="admin_users_panel")
        )
        
    return builder.as_markup()




#===========================creator_panel_kb=============================#
#========================================================================#
# creator_id ni int qilib o'zgartirdik va ortiqcha 'user_status' ni olib tashladik
def creator_panel_kb(creator_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # config.CREATOR_ID ham int bo'lishi kerak
    if creator_id == config.CREATOR_ID:
        builder.row(
            types.InlineKeyboardButton(text="👑 Barcha adminlarni boshqarish", callback_data="creator_admin_panel")
        )
        builder.row(
            types.InlineKeyboardButton(text="📊 To'liq statistika", callback_data="creator_statistics"),
            types.InlineKeyboardButton(text="🗄️ Baza control", callback_data="creator_db_panel")
        )
    
    return builder.as_markup()






#============================get_ranked_kb===============================#
#========================================================================#
# keyboards/inline.py faylida:
def get_ranked_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🎬 Anime Reyting", callback_data="Anime_ranked"),
        types.InlineKeyboardButton(text="🏆 User Reyting", callback_data="User_ranked")
    )
    return builder.as_markup()






#==============================vip_buy_kb================================#
#========================================================================#
def vip_buy_kb(is_vip: bool) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    
    builder.row(
        types.InlineKeyboardButton(text="💎 VIP  olish", callback_data="buy_vip_med")
    )    
    builder.row(
        types.InlineKeyboardButton(text="🎁 Ball yig'ish", callback_data="get_ref_link"),
        types.InlineKeyboardButton(text="👤 Kabinet", callback_data="cabinet")
    )
    return builder.as_markup()



#==============================cabinet_kb================================#
#========================================================================#


def cabinet_kb():

    builder = InlineKeyboardBuilder()
    
    builder.row(types.InlineKeyboardButton(text="💎 VIP sotib olish", callback_data="buy_vip_menu"))
      
    builder.row(
        types.InlineKeyboardButton(text="🎁 Ball yig'ish", callback_data="get_ref_link"),
        types.InlineKeyboardButton(text="🌐 Saytdagi profil", url="https://aninowuz.uz/profile")
    )
    return builder.as_markup()






#============================admin_channels_kb===========================#
#========================================================================#
def admin_channels_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel"))
    builder.row(types.InlineKeyboardButton(text="📋 Kanal ro'yxati", callback_data="list_channels"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"))
    return builder.as_markup()





#============================admin_channels_kb===========================#
#========================================================================#
def anime_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Anime qo'shish", callback_data="add_anime"))
    builder.row(types.InlineKeyboardButton(text="📋 Anime ro'yxati", callback_data="list_anime"))
    builder.row(types.InlineKeyboardButton(text="➖ Anime  o'chirish", callback_data="remove_anime"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"))
    return builder.as_markup()





#=============================admin_advert_kb============================#
#========================================================================#
def admin_addert_kb():
    builder = InlineKeyboardBuilder()
    
    # 1. Asosiy amal (Kanal bilan ishlash)
    builder.row(
        types.InlineKeyboardButton(text="📢 Kanaldan reklama", callback_data="channel_add")
    )
    
    # 2. Vaqt bo'yicha guruhlash (UX uchun qulay)
    builder.row(
        types.InlineKeyboardButton(text="📅 Kunlik", callback_data="day_add"),
        types.InlineKeyboardButton(text="🗓 Haftalik", callback_data="week_add"),
        types.InlineKeyboardButton(text="🗓 Oylik", callback_data="moth_add")
    )
    
    # 3. Navigatsiya
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_advertisement")
    )
    
    return builder.as_markup()





#=============================admin_add_kb============================#
#========================================================================#
def admin_add_kb():
    builder = InlineKeyboardBuilder()
    
    # Reklama funksiyalari (Guruhlangan)
    builder.row(
        types.InlineKeyboardButton(text="📢Reklama yuborish", callback_data="admin_advert")
    )
    builder.row(
        types.InlineKeyboardButton(text="📊 Reklama statistikasi", callback_data="ad_stats"),
    )
    builder.row(
        types.InlineKeyboardButton(text="⏳ Reklama tarixi", callback_data="ad_history")
    )
    
    # Navigatsiya (Har doim alohida qatorda)
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")
    )
    
    return builder.as_markup()






#=============================admin_vip_kb===============================#
#========================================================================#
def admin_vip_kb():
    builder = InlineKeyboardBuilder()

    builder.row(
        types.InlineKeyboardButton(text="➕Vip qo'shish", callback_data="admin_add_vip")
    )
    builder.row(
        types.InlineKeyboardButton(text="📃 Vip ro'yxati", callback_data="admin_list_vip")
    )
    builder.row(
        types.InlineKeyboardButton(text="➖Vip o'chrish", callback_data="admin_del_vip")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")
    )
    return builder.as_markup()



#===========================admin_add_vip_kb=============================#
#========================================================================#
def admin_add_vip_kb():
    builder = InlineKeyboardBuilder()
    
    # 1. Muddatlarni guruhlash (UX: o'sish tartibida)
    # 1 va 3 oylikni bitta qatorga, 6 oy va 1 yillikni keyingisiga qo'yamiz
    builder.row(
        types.InlineKeyboardButton(text="🗓 1 oylik", callback_data="vip_1m"),
        types.InlineKeyboardButton(text="🗓 3 oylik", callback_data="vip_3m")
    )
    builder.row(
        types.InlineKeyboardButton(text="🗓 6 oylik", callback_data="vip_6m"),
        types.InlineKeyboardButton(text="🏆 1 yillik", callback_data="vip_12m")
    )
    
    # 2. Navigatsiya
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_vip_panel")
    )
    
    return builder.as_markup()







#===========================admin_add_vip_kb=============================#
#========================================================================#
def admin_users_panel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🔍 Foydalanuvchini qidirish", callback_data="search_user")
        
    )
    builder.row(
        types.InlineKeyboardButton(text="👑 VIP berish/olish", callback_data="admin_add_vip")
        
    )
    builder.row(
        types.InlineKeyboardButton(text="🚫 Bloklanganlar ro'yxati", callback_data="blocked_users")
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"))
    return builder.as_markup()





#===========================creator_admin_kb=============================#
#========================================================================#
def creator_admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="creator_add_admin")
    )
    builder.row(
        types.InlineKeyboardButton(text="📋 Admin ro'yxati", callback_data="creator_list_admin")
    )
    builder.row(
        types.InlineKeyboardButton(text="➖ Admin o'chirish", callback_data="creator_remove_admin")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="creator_panel")
    )
    return builder.as_markup()





#==========================creator_db_panel_kb===========================#
#========================================================================#
def creator_db_panel_kb():
    builder = InlineKeyboardBuilder()
    
    # 1. Asosiy monitoring
    builder.row(
        types.InlineKeyboardButton(text="📊 Statistika db", callback_data="db_stats"),
        types.InlineKeyboardButton(text="⚙️ Adminlar", callback_data="db_admins")
    )
    
    # 2. Boshqaruv (Backup va Reklama)
    builder.row(
        types.InlineKeyboardButton(text="🔄 Backup", callback_data="db_backup"),
        types.InlineKeyboardButton(text="📈 Reklamalar", callback_data="db_ads_active")
    )
    
    # 3. Tozalash (Xavfli amallar)
    builder.row(
        types.InlineKeyboardButton(text="🧹 Loglar", callback_data="db_clean_logs"),
        types.InlineKeyboardButton(text="🗑 Outbox", callback_data="db_clean_outbox")
    )
    # 4. Import/Export (Ma'lumotlarni saqlash va tiklash)
    builder.row(
        types.InlineKeyboardButton(text=" import qilish", callback_data="db_import"),
        types.InlineKeyboardButton(text="export qilish", callback_data="db_export")
    )
    
    # 5. Navigatsiya
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="creator_panel")
    )
    
    return builder.as_markup()





#===========================buy_vip_med_kb===============================#
#========================================================================#
def buy_vip_med_kb(user_id: int):
    # Admin username va URL ni shakllantirish
    admin_username = "Khudoyqulov_pg"
    raw_msg = f"Assalomu alaykum, VIP sotib olmoqchiman. ID: {user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"
    
    builder = InlineKeyboardBuilder()
    
    # 1. Tariflar
    builder.row(
        types.InlineKeyboardButton(text="🗓 1 oylik", callback_data="buyer_vip_1m"),
        types.InlineKeyboardButton(text="🗓 3 oylik", callback_data="buyer_vip_3m")
    )
    builder.row(
        types.InlineKeyboardButton(text="🗓 6 oylik", callback_data="buyer_vip_6m"),
        types.InlineKeyboardButton(text="🏆 1 yillik", callback_data="buyer_vip_12m")
    )
    # 2. 
    builder.row(
        types.InlineKeyboardButton(text="💎 Ballarga almashitirish", callback_data="buy_vip_bonus")
    )
    # 3. Admin bilan bog'lanish (Dinamik URL bilan)
    builder.row(
        types.InlineKeyboardButton(text="💬 Admin bilan bog'lanish", url=admin_url)
    )
    
    # 4. Navigatsiya
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="buy_vip_menu")
    )
    
    return builder.as_markup()




#==========================add_anime_main_kb=============================#
#========================================================================#
def add_anime_main_kb():
    builder = InlineKeyboardBuilder()
    
    # 1. Asosiy monitoring
    builder.row(
    types.InlineKeyboardButton(
        text="➕ Anime qo'shish", 
        callback_data="AnimeMenuCallbacks.ADD_ANIME"  # String o'zgaruvchi o'zi uzatiladi
        )
    )
    
    builder.row(
        types.InlineKeyboardButton(text="➕Qism qo'shish", callback_data="list_anime")
    )

    builder.row(
         types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel")
    )
    
    return builder.as_markup()