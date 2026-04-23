from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.cache import valkey
from database.models import Channel, DBUser 
from keyboards.reply import get_main_menu
from config import config


CREATOR_ID = config.CREATOR_ID 

router = Router()

async def get_sub_keyboard(session: AsyncSession) -> types.InlineKeyboardMarkup:
    # Keshdan olishga harakat qilamiz
    channels_data = await valkey.get("custom", "active_channels_list")
    
    if not channels_data:
        # Agar keshda bo'lmasa bazadan olamiz (yoki check_subscription'ni chaqiramiz)
        stmt = select(Channel).where(Channel.is_active == True)
        result = await session.execute(stmt)
        active_channels = result.scalars().all()
        channels_data = [{"id": ch.channel_id, "url": ch.url, "title": ch.title} for ch in active_channels]
    
    buttons = []
    for ch in channels_data:
        buttons.append([types.InlineKeyboardButton(text=ch['title'], url=ch['url'])])
    
    buttons.append([types.InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession) -> bool:
    # 1. Keshdan kanallarni qidiramiz
    cached_channels = await valkey.get("custom", "active_channels_list")
    
    if cached_channels:
        channels_data = cached_channels
    else:
        # 2. Keshda bo'lmasa, bazadan olamiz
        stmt = select(Channel).where(Channel.is_active == True)
        result = await session.execute(stmt)
        active_channels = result.scalars().all()
        
        channels_data = [{"id": ch.channel_id, "url": ch.url, "title": ch.title} for ch in active_channels]
        
        # 3. Keshga yozamiz (15 daqiqaga)
        await valkey.set_custom("custom:active_channels_list", channels_data, expire=900)

    if not channels_data:
        return True

    for ch in channels_data:
        try:
            member = await bot.get_chat_member(chat_id=ch['id'], user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            continue
    return True

# ================= /start =================
@router.message(CommandStart())
async def cmd_start(message: types.Message, user: DBUser, session: AsyncSession, bot: Bot):
    await valkey.set(user, expire=3600)  # foydalanuvchi (1 soatga) ga keshga saqlaymiz, har safar yangilaymiz
    # 1. Creator tekshiruvi
    
    if message.from_user.id == CREATOR_ID:
        return await message.answer(
            f"Xush kelibsiz, 👑 <b>ASOSIY CREATOR</b>!",
            reply_markup=get_main_menu(user_id=message.from_user.id, status="creator")
        )

    # 2. Obuna tekshiruvi (Admin va VIP dan tashqari)
    if user.status not in ["admin", "vip"]:
        is_subscribed = await check_subscription(bot, message.from_user.id, session)
        if not is_subscribed:
            kb = await get_sub_keyboard(session)
            return await message.answer(
                "⚠️ Botdan foydalanish uchun kanallarimizga obuna bo'ling:",
                reply_markup=kb
            )

    # 3. Oddiy foydalanuvchi yoki Admin uchun start
    await message.answer(
        f"Xush kelibsiz, <b>{message.from_user.full_name}</b>!\n"
        f"Statusingiz: <b>{user.status}</b>",
        reply_markup=get_main_menu(user_id=message.from_user.id, status=user.status)
    )

# ================= Callback Handler =================
@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery, user: DBUser, session: AsyncSession, bot: Bot):
    is_subscribed = await check_subscription(bot, callback.from_user.id, session)

    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer(
            f"✅ Rahmat! Obuna tasdiqlandi.\nXush kelibsiz, <b>{callback.from_user.full_name}</b>!",
            reply_markup=get_main_menu(user_id=callback.from_user.id, status=user.status)
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmagansiz!", show_alert=True)