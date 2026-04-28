from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
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