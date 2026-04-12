from aiogram import Router, types, Bot
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import DBUser

router = Router()

# Hozircha bo'sh qoldiramiz. Bo'sh bo'lsa, hamma "True" bo'lib o'taveradi.
CHANNELS = [] 

async def check_subscription(bot: Bot, user_id: int):
    # Agar kanallar ro'yxati bo'sh bo'lsa, avtomatik True qaytaramiz
    if not CHANNELS:
        return True
        
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            # Agar bot kanalga admin bo'lmasa yoki kanal topilmasa ham False qaytadi
            return False
    return True

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: DBUser, session: AsyncSession, bot: Bot):
    user_id = message.from_user.id
    
    # VIP va Adminlar doim o'tadi, qolganlar uchun kanal bor-yo'qligini tekshiramiz
    if user.status not in ["admin", "vip"]:
        is_subscribed = await check_subscription(bot, user_id)
        
        if not is_subscribed:
            # Faqat CHANNELS ichida kanal bo'lsa va foydalanuvchi a'zo bo'lmasa ishlaydi
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Obuna bo'lish", url=f"https://t.me/{CHANNELS[0][1:]}")],
                [types.InlineKeyboardButton(text="Tekshirish ✅", callback_data="check_sub")]
            ])
            return await message.answer(
                "Botdan foydalanish uchun kanallarimizga obuna bo'ling:",
                reply_markup=keyboard
            )

    # --- ASOSIY MENYU (Sxemangizdagi Menu_cmd) ---
    kb = [
        [types.KeyboardButton(text="🔍 Anime qidirish"), types.KeyboardButton(text="👤 Shaxsiy kabinet")],
        [types.KeyboardButton(text="🌟 Reyting"), types.KeyboardButton(text="❓ Qo'llanma")],
        [types.KeyboardButton(text="💎 VIP sotib olish"), types.KeyboardButton(text="📢 Reklama berish")]
    ]
    
    if user.status == "admin":
        kb.append([types.KeyboardButton(text="⚙️ SC ADMIN PANEL")])

    main_menu = types.ReplyKeyboardMarkup(
        keyboard=kb, 
        resize_keyboard=True,
        input_field_placeholder="Bo'limni tanlang..."
    )

    await message.answer(
        f"Xush kelibsiz, {message.from_user.full_name}!\nSizning statusingiz: <b>{user.status}</b>",
        reply_markup=main_menu
    )