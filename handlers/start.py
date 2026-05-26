from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards.reply import get_main_menu
from config import config

router = Router()

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
    """ 
    Foydalanuvchi kanallarga a'zo bo'lib '🔄 Obunani Tekshirish' tugmasini bossa, 
    agar obuna bo'lgan bo'lsa Middleware uni to'g'ridan-to'g'ri shu handlerga o'tkazadi.
    """
    user_id = callback.from_user.id
    
    # 🟢 A'lo darajadagi UX: Avval foydalanuvchiga yuklanish soatni to'xtatib javob beramiz
    await callback.answer("Xush kelibsiz! 🎉" )
    
    # 🟢 Yangi xabarni yuboramiz
    await callback.message.answer(
        text="✅ Rahmat! Obunangiz muvaffaqiyatli tasdiqlandi.\n🤖 Marhamat, botdan foydalanishingiz mumkin:",
        reply_markup=get_main_menu(
            is_vip=False, 
            is_admin=False, 
            is_creator=(user_id == config.CREATOR_ID)
        )
    )
    
    # 🟢 Oldingi majburiy obuna xabarini try-except ichida xavfsiz o'chiramiz
    try:
        await callback.message.delete()
    except Exception:
        pass