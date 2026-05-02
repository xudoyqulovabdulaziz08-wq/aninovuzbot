import logging
import asyncio
import pytz
from aiogram import types, Bot, F, Router
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from aiogram.fsm.context import FSMContext

from database.cache import valkey
from database.models import Channel, DBUser 
from keyboards.reply import get_main_menu
from config import config

logger = logging.getLogger("StartHandler")
router = Router()

# --- GLOBAL CONSTANTS & LOCKS ---
CH_NS, CH_ID = "custom", "active_channels"
_channel_fetch_lock = asyncio.Lock()

# --- UTILS / HELPERS ---

async def _get_active_channels(session: AsyncSession) -> list:
    """
    Aktiv kanallarni keshdan yoki bazadan olish (Stampede protection bilan).
    """
    channels = await valkey.get(CH_NS, CH_ID)
    if channels is not None:
        return channels

    async with _channel_fetch_lock:
        # Double-checked locking
        channels = await valkey.get(CH_NS, CH_ID)
        if channels is not None:
            return channels

        try:
            stmt = select(Channel).where(Channel.is_active == True)
            result = await session.execute(stmt)
            db_channels = result.scalars().all()
            
            channels_data = [
                {"id": ch.channel_id, "url": ch.url, "title": ch.title} 
                for ch in db_channels
            ]
            
            # Keshga 15 daqiqaga yozish
            await valkey.set_custom(CH_NS, CH_ID, channels_data, expire=900)
            return channels_data
        except Exception as e:
            logger.critical(f"Critical DB failure in _get_active_channels: {e}")
            return []

async def check_subscription(bot: Bot, user_id: int, session: AsyncSession) -> tuple[bool, list]:
    """
    Foydalanuvchining barcha majburiy kanallarga a'zoligini tekshiradi.
    """
    channels = await _get_active_channels(session)
    if not channels:
        return True, []

    semaphore = asyncio.Semaphore(5) # API yuklamasini cheklash
    
    async def _strict_check(ch):
        async with semaphore:
            try:
                member = await bot.get_chat_member(chat_id=ch['id'], user_id=user_id)
                allowed = ["member", "administrator", "creator"]
                if member.status not in allowed:
                    return ch
            except Exception:
                return ch # API xato bersa ham obuna bo'lmagan deb hisoblaymiz (Strict mode)
        return None

    check_results = await asyncio.gather(*[_strict_check(ch) for ch in channels])
    not_joined = [res for res in check_results if res is not None]
    
    return len(not_joined) == 0, not_joined

async def get_sub_keyboard(missing_channels: list) -> types.InlineKeyboardMarkup:
    """
    Obuna bo'lmagan kanallar uchun tracking tugmalarini yasaydi.
    """
    buttons = []
    for ch in missing_channels:
        # Har bir kanal uchun redirect handlerga yo'naltiramiz
        buttons.append([types.InlineKeyboardButton(
            text=f"📌 {ch['title']}", 
            callback_data=f"go_to_channel:{ch['id']}"
        )])
    
    # Umumiy tekshirish tugmasi
    buttons.append([types.InlineKeyboardButton(
        text="✅ Tasdiqlash", 
        callback_data="check_sub:all"
    )])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

# --- HANDLERS ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, user: any, session: AsyncSession, bot: Bot, state: FSMContext):
    """
    /start buyrug'i uchun asosiy handler. 
    Referral tizimi va obuna tekshiruvini boshqaradi.
    """
    await state.clear()
    args = message.text.split()
    
    # Yangi user ekanligini tekshirish (Middleware'dan kelgan joined_at bo'yicha)
    user_joined = getattr(user, 'joined_at', None)
    now_utc = datetime.now(timezone.utc)
    
    if user_joined:
        user_joined = user_joined.replace(tzinfo=timezone.utc) if user_joined.tzinfo is None else user_joined
        is_new_user = (now_utc - user_joined).total_seconds() < 60
    else:
        is_new_user = True # Agar joined_at bo'lmasa, yangi user deb hisoblaymiz

    # 1. REFERRAL TIZIMI (Bog'lash qismi)
    if len(args) > 1 and getattr(user, 'referred_by', None) is None and is_new_user:
        try:
            referrer_id = int(args[1])
            if referrer_id != message.from_user.id:
                # Bazadagi modelni yangilash uchun sessiyadan foydalanamiz
                stmt = select(DBUser).where(DBUser.user_id == message.from_user.id)
                res = await session.execute(stmt)
                db_user = res.scalar_one_or_none()
                
                if db_user and db_user.referred_by is None:
                    db_user.referred_by = referrer_id
                    await session.commit()
                    logger.info(f"User {db_user.user_id} referred by {referrer_id}")
        except (ValueError, IndexError) as e:
            logger.warning(f"Referral parsing error: {e}")

    # 2. PRIVILEGE CHECK (Creator/Admin/VIP)
    status = getattr(user, 'status', 'user')
    is_vip = getattr(user, 'is_vip', False)

    if status in ["creator", "admin"] or is_vip or message.from_user.id == config.CREATOR_ID:
        return await message.answer(
            f"👑 Xush kelibsiz, <b>{message.from_user.full_name}</b>!",
            reply_markup=get_main_menu(user_id=message.from_user.id, is_vip=is_vip, status=status),
            parse_mode="HTML"
        )

    # 3. KANALLARGA OBUNA TEKSHIRUVI
    is_subbed, missing = await check_subscription(bot, message.from_user.id, session)
    
    if not is_subbed:
        kb = await get_sub_keyboard(missing)
        return await message.answer(
            "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )

    # 4. SUCCESS ENTRY
    await message.answer(
        f"👋 Xush kelibsiz, <b>{message.from_user.full_name}</b>!\n<b>AniNowuz</b> botiga xush kelibsiz.",
        reply_markup=get_main_menu(user_id=message.from_user.id, is_vip=is_vip, status=status),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("go_to_channel:"))
async def track_channel_redirect(callback: types.CallbackQuery, session: AsyncSession):
    """
    Foydalanuvchini kanalga yo'naltirish va oxirgi kanalini saqlash.
    """
    try:
        ch_id = int(callback.data.split(":")[1])
        
        # Kanalni topish
        result = await session.execute(select(Channel).where(Channel.channel_id == ch_id))
        channel = result.scalar_one_or_none()

        if not channel:
            return await callback.answer("❌ Kanal topilmadi!", show_alert=True)

        # Oxirgi kanalni DB da belgilash (Tracking)
        await session.execute(
            update(DBUser)
            .where(DBUser.user_id == callback.from_user.id)
            .values(last_redirected_channel=str(ch_id))
        )
        await session.commit()

        text = (
            f"📢 <b>Kanalga obuna bo‘ling</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Kanal: <b>{channel.title}</b>\n\n"
            f"1️⃣ Quyidagi tugma orqali kanalga o‘ting\n"
            f"2️⃣ Obuna bo‘ling\n"
            f"3️⃣ So'ngra 'Tasdiqlash' tugmasini bosing"
        )

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📢 Kanalga o‘tish", url=channel.url)],
            [types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"check_sub:{ch_id}")]
        ])

        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            
        await callback.answer()

    except Exception as e:
        logger.error(f"Redirect tracking error: {e}")
        await callback.answer("⚠️ Xatolik yuz berdi", show_alert=True)

@router.callback_query(F.data.startswith("check_sub"))
async def check_sub_callback(callback: types.CallbackQuery, user: any, session: AsyncSession, bot: Bot):
    """
    Obunani qayta tekshirish va referral ballarini berish.
    """
    is_subbed, missing = await check_subscription(bot, callback.from_user.id, session)

    if is_subbed:
        # ✅ REFERRAL BALL BERISH (Faqat to'liq obuna bo'lganda)
        # Modelni sessiya orqali yuklaymiz
        stmt = select(DBUser).where(DBUser.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        db_user = res.scalar_one_or_none()

        if db_user and db_user.referred_by and db_user.referred_by_channel != "done":
            # Referrer (taklif qilgan) ni bazadan topish
            ref_stmt = select(DBUser).where(DBUser.user_id == db_user.referred_by)
            ref_res = await session.execute(ref_stmt)
            referrer = ref_res.scalar_one_or_none()

            if referrer:
                # Ballarni hisoblash
                referrer.points += 10
                referrer.referral_count += 1
                db_user.referred_by_channel = "done" # Flagni o'rnatish
                
                await session.commit()
                
                # Referrer keshini o'chiramiz, middleware yangisini o'qishi uchun
                await valkey.delete("db_users", referrer.user_id)

                try:
                    await bot.send_message(
                        chat_id=referrer.user_id,
                        text=f"🎊 <b>Yangi referral!</b>\nFoydalanuvchi obuna bo'ldi, sizga <b>10 ball</b> berildi! 🔥",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        # UI TOZALASH
        try:
            await callback.message.delete()
        except:
            pass
            
        status = getattr(user, 'status', 'user')
        is_vip = getattr(user, 'is_vip', False)

        await callback.message.answer(
            "✅ <b>Tabriklaymiz!</b> Barcha obunalar tasdiqlandi.",
            reply_markup=get_main_menu(user_id=callback.from_user.id, is_vip=is_vip, status=status),
            parse_mode="HTML"
        )
    else:
        # Hali obuna bo'lmagan bo'lsa, alert chiqarish va tugmalarni yangilash
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)
        try:
            new_kb = await get_sub_keyboard(missing)
            await callback.message.edit_reply_markup(reply_markup=new_kb)
        except:
            pass