import asyncio
from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from database.repository import ChannelRepository
from database.cache import cache_manager

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Callback yoki Message emas bo'lsa, o'tkazib yuborish (masalan, MyChatMember)
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        channels = await cache_manager.get_channels()
        
        if not channels:
            session = data["session_pool"]()
            try:
                db_channels = await ChannelRepository.get_all_active_channels(session)
                channels = [{"id": c.channel_id, "url": c.url, "title": c.title} for c in db_channels]
                await cache_manager.set_channels(channels)
            finally:
                await session.close()

        if not channels:
            return await handler(event, data)

        # 🚀 Optimallashtirilgan tekshiruv (Parallel)
        async def check_single(ch):
            try:
                member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
                if member.status in ["left", "kicked"]:
                    return ch
            except:
                return None
            return None

        results = await asyncio.gather(*(check_single(ch) for ch in channels))
        not_subscribed = [r for r in results if r is not None]

        if not_subscribed:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['url'])] for ch in not_subscribed
            ] + [[InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")]])
            
            await event.answer("Botdan foydalanish uchun kanallarga obuna bo'ling:", reply_markup=kb)
            return

        return await handler(event, data)