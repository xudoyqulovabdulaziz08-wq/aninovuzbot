# keyboards/reply.py
from aiogram import types
from config import config

def get_main_menu(user_id: int, status: str) -> types.ReplyKeyboardMarkup:
    """Asosiy menyu klaviaturasi - Creator ikkala panelni ham ko'ra oladi."""
    
    kb = [
        [types.KeyboardButton(text="🔍 Anime qidirish"), types.KeyboardButton(text="👤 Shaxsiy kabinet")],
        [types.KeyboardButton(text="🌟 Reyting"), types.KeyboardButton(text="❓ Qo'llanma")],
        [types.KeyboardButton(text="💎 VIP sotib olish"), types.KeyboardButton(text="📢 Reklama berish")]
    ]
    
    # 1. Agar foydalanuvchi Asosiy Creator bo'lsa
    if user_id == config.CREATOR_ID:
        # Creatorga ikkala tugmani ham chiqaramiz
        kb.append([
            types.KeyboardButton(text="⚙️ SC ADMIN PANEL"),
            types.KeyboardButton(text="👑 CREATOR PANEL")
        ])
        
    # 2. Agar foydalanuvchi faqat oddiy admin bo'lsa
    elif status == "admin":
        kb.append([types.KeyboardButton(text="⚙️ SC ADMIN PANEL")])
        
    return types.ReplyKeyboardMarkup(
        keyboard=kb, 
        resize_keyboard=True, 
        input_field_placeholder="Bo'limni tanlang..."
    )