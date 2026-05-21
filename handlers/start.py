from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart

# 1. Router obyektini yaratamiz
router = Router(name="start_router")

# 2. Handlerga filtrlarni yangi uslubda beramiz
@router.message(CommandStart())
async def command_start_handler(message: Message):
    """
    Foydalanuvchi /start bosganda ishlaydigan handler
    """
    await message.answer(
        f"👋 Assalomu alaykum, {message.from_user.full_name}!\n\n"
        "Aninovuz botiga xush kelibsiz! Tizim ultra rejimda muvaffaqiyatli ishga tushdi. 🚀"
    )

# Agar matnli xabarlar uchun ham handler kerak bo'lsa:
@router.message(F.text == "Menu")
async def menu_handler(message: Message):
    await message.answer("Bosh menyu yuklanmoqda... 📋")