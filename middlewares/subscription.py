# middlewares/subscription.py
import asyncio
import logging
from typing import Any, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from database.repository import ChannelRepository
from database.cache import valkey

# Ikki xil logger takrorlangan edi, bittasi olib tashlandi.
logger = logging.getLogger("CheckSubscriptionMiddleware")

class CheckSubscriptionMiddleware(BaseMiddleware):
    
    async def __call__(self, handler: Any, event: Any, data: Dict[str, Any]) -> Any:
        # 1. Faqat xabarlar va callback query so'rovlarini tekshiramiz
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # 2. 🚀 VIP, Admin va System so'rovlari uchun Bypass (Tekshirmay o'tkazish)
        user_data = data.get("user", {})
        if user_data.get("is_system") or user_data.get("is_vip") or user_data.get("status") in ["admin", "owner"]:
            return await handler(event, data)

        user_id = data["event_from_user"].id
        bot = data["bot"]
        
        # "check_sub" tugmasi bosilganda biz keshni inobatga olmasdan bazani majburiy yangilaymiz
        force_check = isinstance(event, CallbackQuery) and event.data == "check_sub"

        # 3. 🚀 RATE LIMIT HIMOYASI (API ni qiynamaslik uchun 15 daqiqalik kesh)
        if not force_check and valkey.is_alive:
            try:
                # Agar user yaqinda tekshirilgan va obunasi tasdiqlangan bo'lsa, API ga bormaymiz
                is_subbed = await valkey.get(table="sub_status", obj_id=str(user_id))
                if is_subbed == "ok":
                    return await handler(event, data)
            except Exception as e:
                logger.debug(f"Sub cache get error: {e}")

        # 4. DbSessionMiddleware taqdim etgan xavfsiz proxy sessiyani olish
        session = data.get("session")
        if not session:
            logger.warning("⚠️ DbSessionMiddleware sessiyasi topilmadi, tekshiruv o'tkazib yuborildi.")
            return await handler(event, data)

        # 5. Faol kanallarni L1/L2 kesh orqali (0ms da) yuklab olish
        try:
            channels = await ChannelRepository.get_all_active_channels(session)
        except Exception as e:
            logger.error(f"🚨 Middleware kanallarni olishda xato: {e}")
            return await handler(event, data)

        # Majburiy kanallar bazada yo'q bo'lsa, erkin o'tkazamiz
        if not channels:
            return await handler(event, data)

        # 6. Telegram API orqali parallel obunani tekshirish
        async def check_single(ch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            try:
                chat_id = int(ch["channel_id"])
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                
                if member.status in ["left", "kicked"]:
                    return ch
            except Exception as api_err:
                logger.debug(f"⚠️ Telegram API xatosi (Kanal ID: {ch.get('channel_id')}): {api_err}")
                # Tarmoq xatosi yoki bot kanalda admin bo'lmasa userni qiynamaslik uchun o'tkazamiz
                return None
            return None

        # Barcha kanallarni parallel tekshirish (Fast gather)
        results = await asyncio.gather(*(check_single(ch) for ch in channels))
        not_subscribed = [r for r in results if r is not None]

        # ======================================================
        # 🛑 Agar foydalanuvchi obuna bo'lmagan kanallar aniqlansa:
        # ======================================================
        if not_subscribed:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['url'])] for ch in not_subscribed
            ] + [[InlineKeyboardButton(text="🔄 Obunani tasdiqlash", callback_data="check_sub")]])
            
            text = "⚠️ <b>Botdan to'liq foydalanish uchun quyidagi homiy kanallarga a'zo bo'ling:</b>"
            
            if isinstance(event, Message):
                await event.answer(text=text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                try:
                    # Flicker/Miltillash oldini olish (FAQAT o'zgarsa edit qilinadi)
                    await event.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
                except TelegramBadRequest as e:
                    if "message is not modified" not in str(e):
                        await event.message.answer(text=text, reply_markup=kb, parse_mode="HTML")
                
                await event.answer("⚠️ Hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)
            
            # Keshni bekor qilamiz (agar oldin obuna bo'lib, hozir chiqib ketgan bo'lsa)
            if valkey.is_alive:
                try:
                    await valkey.invalidate(table="sub_status", obj_id=str(user_id), broadcast=False)
                except Exception:
                    pass

            return  # 🛑 Bot oqimi shu yerda uziladi, handler bajarilmaydi.

        # ======================================================
        # 🟢 Agarda foydalanuvchi HAMMA kanalga obuna bo'lgan bo'lsa:
        # ======================================================
        
        # Bot API ni qiynamasligi uchun foydalanuvchini 15 daqiqa (900 soniya) davomida keshlaymiz
        if valkey.is_alive:
            try:
                await valkey.set(table="sub_status", obj_id=str(user_id), data="ok", ttl=900)
            except Exception as e:
                logger.debug(f"Sub cache set error: {e}")

        # Agar bu holat "Obunani tekshirish" tugmasi bosilishidan kelib chiqqan bo'lsa:
        if force_check:
            await event.answer("🎉 Rahmat, obuna muvaffaqiyatli tasdiqlandi!", show_alert=True)
            try:
                await event.message.delete()  # Eski ogohlantirish xabarini o'chiramiz
            except Exception:
                pass
            
            # Agar sizning routeringizda (handlerlar orasida) @dp.callback_query(F.data == "check_sub") 
            # degan maxsus funksiya bo'lmasa, aiogram buni o'tkazib yuboradi va bot to'xtaydi.
            return await handler(event, data)

        # Odatiy xabar yoki callback oqimini o'z holicha davom ettirish
        return await handler(event, data)