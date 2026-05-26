# middlewares/subscription.py
import asyncio
import logging
from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from database.repository import ChannelRepository

logger = logging.getLogger("SubMiddleware")





logger = logging.getLogger("CheckSubscriptionMiddleware")

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # 🛑 TUZATILDI: 'check_sub' bosilganda shunchaki o'tkazib yuborish sharti OLIY TASHLANDI!
        # Chunki u bosilganda pastdagi hamma tekshiruvlar qaytadan ishlashi shart.

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        session_pool = data.get("session_pool")
        if not session_pool:
            return await handler(event, data)

        # O'zgaruvchini oldindan bo'sh ro'yxat qilib e'lon qilamiz
        channels = []
        
        async with session_pool() as session:
            try:
                channels = await ChannelRepository.get_all_active_channels(session)
            except Exception as e:
                logger.error(f"🚨 Middleware kanallarni olishda xato: {e}")
                return await handler(event, data)

        if not channels:
            return await handler(event, data)

        # 🚀 Parallel Telegram API tekshiruvi
        async def check_single(ch):
            try:
                chat_id = int(ch["channel_id"])
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                
                if member.status in ["left", "kicked"]:
                    return ch
            except Exception as api_err:
                logger.error(f"❌ Telegram API xatosi (Kanal ID: {ch.get('channel_id')}): {api_err}")
                return None
            return None

        results = await asyncio.gather(*(check_single(ch) for ch in channels))
        not_subscribed = [r for r in results if r is not None]

        if not_subscribed:
            # Tugmalarni chiroyli tarzda yig'amiz
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['url'])] for ch in not_subscribed
            ] + [[InlineKeyboardButton(text="🔄 Obunani Tekshirish", callback_data="check_sub")]])
            
            text = "⚠️ <b>Botdan foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:</b>"
            
            if isinstance(event, Message):
                await event.answer(text=text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                try:
                    # Silliq ko'rinishi uchun faqat markup va matnni o'zgartiramiz
                    await event.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
                except TelegramBadRequest as e:
                    if "message is not modified" not in str(e):
                        await event.message.answer(text=text, reply_markup=kb, parse_mode="HTML")
                
                # 🟢 TUZATILDI: callback.answer o'rniga event.answer yozildi
                await event.answer("⚠️ Hali hamma kanallarga obuna bo'lmagansiz!", show_alert=True)
            
            return # 🔴 Bot shu yerda to'xtaydi 

        # 🟢 Agar foydalanuvchi hamma kanalga obuna bo'lgan bo'lsa va 'check_sub'ni bosgan bo'lsa:
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            await event.answer("🎉 Rahmat, obuna tasdiqlandi!", show_alert=True)
            try:
                await event.message.delete() # Homiy kanallar xabarini o'chirib tashlaymiz
            except Exception:
                pass
            
            # Bu yerda foydalanuvchiga muvaffaqiyatli o'tganidan keyin asosiy xabarni chiqarish kerak:
            await event.message.answer("🤖 Botimizga xush kelibsiz! Botdan foydalanishingiz mumkin.")
            return

        return await handler(event, data)