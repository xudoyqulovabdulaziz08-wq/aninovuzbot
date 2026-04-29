from aiogram import types
from config import config

def get_main_menu(user_id: int, is_vip: bool, status: str) -> types.ReplyKeyboardMarkup:
    """Asosiy menyu klaviaturasi."""
    
    # Barcha uchun ochiq asosiy tugmalar
    kb = [
        [types.KeyboardButton(text="🔍 Anime qidirish"), types.KeyboardButton(text="👤 Shaxsiy kabinet")],
        [types.KeyboardButton(text="🌟 Reyting"), types.KeyboardButton(text="❓ Qo'llanma")],
        [types.KeyboardButton(text="💎 VIP sotib olish"), types.KeyboardButton(text="📢 Reklama berish")]
    ]

    # VIP foydalanuvchilar uchun maxsus tugma
    # is_vip ni bool (True/False) deb hisoblaymiz
    if is_vip:
        kb.append([types.KeyboardButton(text="🌟 VIP imkoniyatlar")])

    # Admin va Creator uchun tugmalar
    if user_id == config.CREATOR_ID:
        # Creatorga ikkala panelni ham chiqaramiz
        kb.append([
            types.KeyboardButton(text="⚙️ SC ADMIN PANEL"),
            types.KeyboardButton(text="👑 CREATOR PANEL")
        ])
    elif status == "admin":
        # Oddiy admin faqat admin panelni ko'radi
        kb.append([types.KeyboardButton(text="⚙️ SC ADMIN PANEL")])
        
    return types.ReplyKeyboardMarkup(
        keyboard=kb, 
        resize_keyboard=True, 
        input_field_placeholder="Kerakli bo'limni tanlang..."
    )