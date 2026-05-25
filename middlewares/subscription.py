# middlewares/subscription.py
import asyncio
import logging
from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from database.repository import ChannelRepository

logger = logging.getLogger("SubMiddleware")

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        # 🟢 REPOZITORIY O'ZI KESH BILAN REAl-VAQTDA ISHLAYDI
        # Keshda bo'lsa keshdan (0-2ms), bo'lmasa bazadan oladi
        session_pool = data.get("session_pool")
        if not session_pool:
            return await handler(event, data)

        async with session_pool() as session:
            try:
                channels = await ChannelRepository.get_all_active_channels(session)
            except Exception as e:
                logger.error(f"🚨 Middleware kanallarni olishda xato: {e}")
                return await handler(event, data)

        if not channels:
            # Agar kanallar ro'yxati rostdan ham bo'sh bo'lsa o'tkazib yuboradi
            return await handler(event, data)

        # 🚀 Parallel Telegram API tekshiruvi
        async def check_single(ch):
            try:
                # Modeldagi channel_id nomi bu yerda qat'iy int qilinadi
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
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['url'])] for ch in not_subscribed
            ] + [[InlineKeyboardButton(text="🔄 Obunani Tekshirish", callback_data="check_sub")]])
            
            text = "⚠️ **Botdan foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:**"
            
            if isinstance(event, Message):
                await event.answer(text=text, reply_markup=kb, parse_mode="Markdown")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
                except Exception:
                    await event.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")
                await event.answer()
            return

        return await handler(event, data)