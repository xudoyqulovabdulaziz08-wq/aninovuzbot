# start.py
from typing import Any, Dict
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

router.message.outer_middleware(CheckSubscriptionMiddleware())
router.callback_query.outer_middleware(CheckSubscriptionMiddleware())

@router.message(CommandStart())
async def cmd_start(message: Message, user: Dict[str, Any]):
    """ 
    🚀 /start komandasi: Obunadan o'tganlar uchun asosiy menyu.
    💡 DIQQAT: 'user' parametri DbSessionMiddleware orqali tayyor keladi!
    """
    user_id = message.from_user.id
    
    # 1. DbSessionMiddleware taqdim etgan ma'lumotlardan huquqlarni aniqlaymiz
    is_vip = user.get("is_vip", False)
    status = user.get("status", "user")
    is_admin = status in ["admin", "owner"]
    is_creator = (user_id == config.CREATOR_ID)
    
    # 2. Chiroyli va o'ziga jalb qiluvchi UX matn (HTML parse_mode uchun)
    text = (
        f"👋 <b>Assalomu alaykum, {message.from_user.full_name}!</b>\n\n"
        f"🎬 <b>Animnowuz</b> platformasiga xush kelibsiz!\n"
        f"Eng so'nggi va qiziqarli animelarni shu yerdan topishingiz mumkin.\n\n"
        f"👇 <i>Marhamat, kerakli bo'limni tanlang:</i>"
    )
    
    # 3. Dinamik menyuni taqdim etamiz
    await message.answer(
        text=text,
        parse_mode="HTML",
        reply_markup=get_main_menu(
            is_vip=is_vip, 
            is_admin=is_admin, 
            is_creator=is_creator
        )
    )

@router.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery, user: Dict[str, Any]):
    """ 
    ✅ Obunani tasdiqlash tugmasi bosilganda ishlaydi. 
    Middleware buni tekshirib (obuna bo'lsa) o'tkazib yuboradi.
    """
    user_id = callback.from_user.id
    
    # Foydalanuvchi huquqlarini kesh/baza dict idan olamiz
    is_vip = user.get("is_vip", False)
    status = user.get("status", "user")
    is_admin = status in ["admin", "owner"]
    is_creator = (user_id == config.CREATOR_ID)

    # 1. Obuna so'ralgan eski xabarni tozalaymiz (UX miltillashsiz toza bo'lishi uchun)
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    # 2. Muaffaqiyatli obuna haqida iliq xabar
    text = (
        f"🎉 <b>Rahmat! Obunangiz muvaffaqiyatli tasdiqlandi.</b>\n\n"
        f"🤖 Endi botdan to'liq foydalanishingiz mumkin.\n"
        f"👇 <i>Marhamat, asosiy menyudan tanlang:</i>"
    )
    
    await callback.message.answer(
        text=text,
        parse_mode="HTML",
        reply_markup=get_main_menu(
            is_vip=is_vip, 
            is_admin=is_admin, 
            is_creator=is_creator
        )
    )