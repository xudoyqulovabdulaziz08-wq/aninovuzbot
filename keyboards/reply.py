from aiogram import types
from aiogram.utils.keyboard import ReplyKeyboardBuilder





#============================get_main_menu===============================#
#========================================================================#
def get_main_menu(is_vip: bool, is_admin: bool, is_creator: bool) -> types.ReplyKeyboardMarkup:
    """Asosiy menyu klaviaturasi (aiogram 3.x uchun optimallashtirilgan)."""
    builder = ReplyKeyboardBuilder()
    
    # 1. Barcha uchun ochiq asosiy tugmalar
    main_buttons = [
        types.KeyboardButton(text="🔍 Anime qidirish"),
        types.KeyboardButton(text="👤 Shaxsiy kabinet"),
        types.KeyboardButton(text="🌟 Reyting"),
        types.KeyboardButton(text="❓ Qo'llanma"),
        types.KeyboardButton(text="💎 VIP sotib olish"),
        types.KeyboardButton(text="📢 Reklama berish")
    ]
    
    for btn in main_buttons:
        builder.add(btn)
        
    # Asosiy tugmalarni 2 tadan qilib joylashtiramiz
    builder.adjust(2)

    # 2. VIP foydalanuvchilar uchun qo'shimcha qator
    if is_vip:
        builder.row(types.KeyboardButton(text="🌟 VIP imkoniyatlar"))

    # 3. Admin va Creator panellari uchun alohida qatorlar
    if is_creator:
        # Creator har ikkala panelni bitta qatorda ko'radi
        builder.row(
            types.KeyboardButton(text="⚙️ SC ADMIN PANEL"),
            types.KeyboardButton(text="👑 CREATOR PANEL")
        )
    elif is_admin:
        # Oddiy admin faqat admin panelni ko'radi
        builder.row(types.KeyboardButton(text="⚙️ SC ADMIN PANEL"))
        
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Kerakli bo'limni tanlang..."
    )
    