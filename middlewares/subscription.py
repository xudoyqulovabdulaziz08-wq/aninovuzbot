import asyncio
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database.repository import ChannelRepository
from database.cache import cache_manager  # Yoki loyihangizdagi CacheManager

logger = logging.getLogger("SubscriptionMiddleware")

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        # 1. Faqat Message va CallbackQuery eventlarini tekshiramiz
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # "🔄 Tekshirish" tugmasining o'zini cheksiz qulflashga tushmaslik uchun o'tkazib yuboramiz
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        # 2. Kanallarni keshdan qidiramiz
        channels = await cache_manager.get_channels()
        
        # 3. Kesh bo'sh bo'lsa, Lazy tarzda data ichidagi session_pool'dan foydalanamiz
        if not channels:
            session_pool = data.get("session_pool")
            if session_pool:
                async with session_pool() as session:
                    try:
                        db_channels = await ChannelRepository.get_all_active_channels(session)
                        channels = [{"id": c.channel_id, "url": c.url, "title": c.title} for c in db_channels]
                        await cache_manager.set_channels(channels)
                    except Exception as e:
                        logger.error(f"🚨 Middleware kanallarni bazadan olishda xatolik: {e}")
                        channels = []

        # Agar bazada ham, keshda ham kanallar bo'lmasa, silliq o'tkazib yuboramiz
        if not channels:
            return await handler(event, data)

        # 4. 🚀 Parallel (Asyncio.gather) Telegram API orqali tekshiruv
        async def check_single(ch):
            try:
                member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
                if member.status in ["left", "kicked"]:
                    return ch
            except Exception as e:
                logger.debug(f"⚠️ API tekshiruvda xato (Kanal o'chgan yoki bot admin emas): {ch['title']} -> {e}")
                return None
            return None

        results = await asyncio.gather(*(check_single(ch) for ch in channels))
        not_subscribed = [r for r in results if r is not None]

        # 5. 🔴 OBUNA BO'LMAGAN HOLAT (Foydalanuvchini to'xtatish)
        if not_subscribed:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['url'])] for ch in not_subscribed
            ] + [[InlineKeyboardButton(text="🔄 Obunani Tekshirish", callback_data="check_sub")]])
            
            text = "⚠️ **Botdan foydalanish uchun quyidagi homiy kanallarga obuna bo'ling:**"
            
            # UX Tuzatish: Event turiga qarab to'g'ri javob qaytarish
            if isinstance(event, Message):
                await event.answer(text=text, reply_markup=kb, parse_mode="Markdown")
            elif isinstance(event, CallbackQuery):
                # Callback bosilganda xabarni o'zgartiramiz, alert chiqarmaymiz
                try:
                    await event.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
                except Exception:
                    await event.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")
                await event.answer() # Loading holatini yopish uchun
            return

        # 🟢 OBUNA BO'LGAN HOLAT -> Handlerga yo'l ochiladi
        return await handler(event, data)