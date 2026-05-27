# middlewares/subscription.py
import asyncio
import logging
from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from database.repository import ChannelRepository
from typing import Dict, Optional
from typing import Any



logger = logging.getLogger("SubMiddleware")





logger = logging.getLogger("CheckSubscriptionMiddleware")

class CheckSubscriptionMiddleware(BaseMiddleware):
    
    async def __call__(self, handler: Any, event: Any, data: Dict[str, Any]) -> Any:
        # Faqat xabarlar va callback query so'rovlarini tekshiramiz
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        # 🚀 MIDDLEWARE INTEGRATSIYASI: 
        # Qo'lda session_pool ochmaymiz, DbSessionMiddleware tomonidan tayyorlab berilgan 
        # va kesh zanjiriga ulangan proxy sessiyani to'g'ridan-to'g'ri olamiz.
        session = data.get("session")
        if not session:
            logger.warning("⚠️ DbSessionMiddleware sessiyasi topilmadi, tekshiruv o'tkazib yuborildi.")
            return await handler(event, data)

        channels = []
        try:
            # get_all_active_channels yangi tizimda L1 (Local) keshdan 0ms ichida ma'lumot oladi
            channels = await ChannelRepository.get_all_active_channels(session)
        except Exception as e:
            logger.error(f"🚨 Middleware kanallarni olishda xato: {e}")
            return await handler(event, data)

        # Agar majburiy kanallar o'chirilgan bo'lsa, handlerga o'tkazib yuboramiz
        if not channels:
            return await handler(event, data)

        # 🚀 Parallel Telegram API orqali obunani tekshirish funksiyasi
        async def check_single(ch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            try:
                chat_id = int(ch["channel_id"])
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                
                if member.status in ["left", "kicked"]:
                    return ch
            except Exception as api_err:
                logger.error(f"❌ Telegram API xatosi (Kanal ID: {ch.get('channel_id')}): {api_err}")
                # Tarmoq xatosi bo'lsa foydalanuvchini qiynamaslik uchun None qaytaramiz (yoki xohishga ko'ra ch)
                return None
            return None

        # Barcha kanallarni parallel va tezkor tekshirish
        results = await asyncio.gather(*(check_single(ch) for ch in channels))
        not_subscribed = [r for r in results if r is not None]

        # 🛑 Agar foydalanuvchi obuna bo'lmagan kanallar aniqlansa:
        if not_subscribed:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['url'])] for ch in not_subscribed
            ] + [[InlineKeyboardButton(text="🔄 Obunani Tekshirish", callback_data="check_sub")]])
            
            text = "⚠️ <b>Botdan foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:</b>"
            
            if isinstance(event, Message):
                await event.answer(text=text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                try:
                    # Faqat o'zgarish bo'lsagina markup yangilanadi (Flicker/Miltillash oldi olinadi)
                    await event.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
                except TelegramBadRequest as e:
                    if "message is not modified" not in str(e):
                        await event.message.answer(text=text, reply_markup=kb, parse_mode="HTML")
                
                await event.answer("⚠️ Hali hamma kanallarga obuna bo'lmagansiz!", show_alert=True)
            
            return  # 🛑 Bot oqimi shu yerda uziladi, handler bajarilmaydi.

        # 🟢 Agarda foydalanuvchi hamma kanalga obuna bo'lgan bo'lsa:
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            await event.answer("🎉 Rahmat, obuna tasdiqlandi!", show_alert=True)
            try:
                await event.message.delete()  # Eski ogohlantirish xabarini o'chiramiz
            except Exception:
                pass
            # 🔥 CRITICAL FIX: Foydalanuvchi 'check_sub'ni bosganda obuna to'liq tasdiqlansa,
            # bot shunchaki qotib qolmasdan, uning asl so'rovini (masalan start komandasini yoki tugmasini)
            # davom ettirib yuborishi uchun oqim handlerga uzatiladi!
            return await handler(event, data)

        # Agar foydalanuvchi oddiy holatda yozayotgan bo'lsa va obunasi joyida bo'lsa
        return await handler(event, data)