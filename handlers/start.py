# start.py
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards.reply import get_main_menu
from config import config

# Middleware'ni import qilamiz
from middlewares.subscription import CheckSubscriptionMiddleware

router = Router()

# 🔴 MUHIM: Middleware'ni router xabarlari va callback'lari uchun ulash (Outer middleware bo'lishi shart)
router.message.outer_middleware(CheckSubscriptionMiddleware())
router.callback_query.outer_middleware(CheckSubscriptionMiddleware())

@router.message(CommandStart())
async def cmd_start(message: Message):
    """ Middleware obunani tekshirib o'tkazgani uchun, bu yerga faqat OBUNA BO'LGANLAR kiradi """
    user_id = message.from_user.id
    await message.answer(
        text=f"👋 Assalomu alaykum {message.from_user.full_name}!\n\n🤖 Botga xush kelibsiz!",
        reply_markup=get_main_menu(
            is_vip=False, 
            is_admin=False, 
            is_creator=(user_id == config.CREATOR_ID)
        )
    )

@router.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery):
    """ Foydalanuvchi obuna bo'lib qaytsa, shu handler ishlaydi """
    user_id = callback.from_user.id
    await callback.answer("Xush kelibsiz! 🎉")
    
    await callback.message.answer(
        text="✅ Rahmat! Obunangiz muvaffaqiyatli tasdiqlandi.\n🤖 Marhamat, botdan foydalanishingiz mumkin:",
        reply_markup=get_main_menu(
            is_vip=False, 
            is_admin=False, 
            is_creator=(user_id == config.CREATOR_ID)
        )
    )
    try:
        await callback.message.delete()
    except Exception:
        pass