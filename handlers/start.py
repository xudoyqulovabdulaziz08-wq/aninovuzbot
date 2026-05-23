from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from keyboards.reply import get_main_menu
from config import config  # Agar config kerak bo'lsa

# 1. Router obyektini yaratamiz
router = Router(name="start_router")

# 2. Handlerga filtrlarni yangi uslubda beramiz
@router.message(CommandStart())
async def command_start_handler(message: Message):
    """
    Foydalanuvchi /start bosganda ishlaydigan handler
    """
    user_id = message.from_user.id
    
    # Bu yerda rollarni DB yoki middleware'dan olishingiz mumkin.
    # Hozircha namuna uchun qat'iy qiymat kiritamiz:
    is_creator = (user_id == config.CREATOR_ID)
    is_admin = False  # Masalan, DB check: status == "admin"
    is_vip = False    # Masalan, DB check: is_vip == True

    await message.answer(
        text=f"👋 Assalomu alaykum, {message.from_user.full_name}!\n\n"
             "Aninovuz botiga xush kelibsiz!",
        reply_markup=get_main_menu(
            is_vip=is_vip, 
            is_admin=is_admin, 
            is_creator=is_creator
        )
    )

# 3. Matnli "Menu" yoki klaviaturadagi biron bir tugma uchun handler nomi o'zgartirildi
@router.message(F.text == "Menu")
async def menu_handler(message: Message):
    # Bu yerda ham rollarni tekshirib klaviatura qaytarishingiz mumkin
    user_id = message.from_user.id
    is_creator = (user_id == config.CREATOR_ID)
    
    await message.answer(
        text="Bosh menyu yuklanmoqda... 📋",
        reply_markup=get_main_menu(
            is_vip=False, 
            is_admin=False, 
            is_creator=is_creator
        )
    )
    