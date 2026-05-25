import asyncio
import logging
from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from database.repository import ChannelRepository
from database.cache import cache_manager

logger = logging.getLogger("SubMiddleware")

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # 1. Faqat tegishli eventlarni tekshiramiz
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # "check_sub" tugmasi bosilganda cheksiz siklga tushmaslik uchun o'tkazib yuboramiz
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        # 2. Keshdan kanallarni olish
        channels = await cache_manager.get_channels()
        
        # 3. Kesh bo'sh bo'lsa bazadan lazy yuklash (Modellarga o'zgartirish kiritilmaydi)
        if not channels:
            session_pool = data.get("session_pool")
            if not session_pool:
                logger.error("🚨 Middleware ichida session_pool topilmadi!")
                return await handler(event, data)
                
            async with session_pool() as session:
                try:
                    db_channels = await ChannelRepository.get_all_active_channels(session)
                    # Diqqat: Bazadagi ob'ekt nomlarini (c.channel_id) to'g'ri lug'atga o'giramiz
                    channels = []
                    for c in db_channels:
                        channels.append({
                            "id": int(c.channel_id),  # Qat'iy int turiga o'giramiz
                            "url": c.url or "https://t.me",
                            "title": c.title or "Kanal"
                        })
                    
                    if channels:
                        await cache_manager.set_channels(channels)
                        logger.info(f"💾 {len(channels)} ta kanal bazadan olinib, keshga yozildi.")
                except Exception as db_err:
                    logger.error(f"🚨 Kanal jadvalidan ma'lumot olishda xato: {db_err}")
                    # Baza ishlamasa ham foydalanuvchini bloklamaslik uchun:
                    return await handler(event, data)

        if not channels:
            return await handler(event, data)

        # 4. 🚀 Telegram API orqali parallel va xavfsiz tekshiruv
        async def check_single(ch):
            try:
                # Keshdan string bo'lib kelayotgan bo'lishi mumkin, qat'iy int qilamiz
                chat_id = int(ch["id"])
                
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                
                # Agar foydalanuvchi kanalda a'zo bo'lmasa, uni ro'yxatga qo'shamiz
                if member.status in ["left", "kicked"]:
                    return ch
                    
                # Agar a'zo bo'lsa (administrator, creator, member, restricted)
                return None
                
            except Exception as api_err:
                # 🛑 ENG DIQQAT QILINADIGAN NUQTA:
                # Agar Telegram API xato bersa (masalan BotBlocked, ChatNotFound, BotIsNotAdmin),
                # bu foydalanuvchining aybi emas. Shuning uchun uni obuna bo'lmagan deb hisoblamaymiz (None qaytaramiz).
                # Ammo xatoni terminalga chiqarib beradi, muammoni ko'rasiz:
                logger.error(f"⚠️ API tekshira olmadi! Kanal: {ch.get('title')} (ID: {ch.get('id')}). Xato: {api_err}")
                return None

        # Hamma kanallarni bir vaqtning o'zida (Parallel) tekshiramiz
        results = await asyncio.gather(*(check_single(ch) for ch in channels))
        not_subscribed = [r for r in results if r is not None]

        # 5. Obuna bo'lmagan kanallar ro'yxati mavjud bo'lsa foydalanuvchini to'xtatamiz
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

        # 🟢 Agar hamma kanalga obuna bo'lgan bo'lsa, keyingi handlerga o'tadi
        return await handler(event, data)