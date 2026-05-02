import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from html import escape

from database.models import DBUser, Channel
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from datetime import datetime
from sqlalchemy import update
import pytz

router = Router()

# FSM Holatlari
#====================================

class AddChannel(StatesGroup):
    waiting_for_info = State()  # ID va Linkni kutish

#====================================

def paginate(data: list, page: int, limit: int = 5):
    """Ro'yxatni sahifalarga bo'lib beruvchi yordamchi funksiya"""
    start = (page - 1) * limit
    end = start + limit
    return data[start:end]


#====================================
@router.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()



#================Channel Menu=====================

@router.callback_query(F.data == "admin_channels")
async def admin_channels(callback: types.CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    
    # Barcha kanallarni olish (faol va nofaol)
    result = await session.execute(select(Channel).order_by(Channel.created_at.desc()))
    channels = result.scalars().all()

    # Statistika hisoblash
    active_count = sum(1 for ch in channels if ch.is_active)
    total_count = len(channels)

    text = (
        "<b>📢 KANALLARNI BOSHQARISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Umumiy kanallar:</b> {total_count} ta\n"
        f"✅ <b>Faol holatda:</b> {active_count} ta\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
    )

    if channels:
        text += "\n📌 <b>Oxirgi qo'shilganlar:</b>\n"
        # Faqat oxirgi 5 tasini qisqa ro'yxat sifatida ko'rsatish
        for ch in channels[:5]:
            status = "✅" if ch.is_active else "❌"
            text += f"{status} {ch.title[:20]}\n"
    else:
        text += "\n⚠️ Hozircha bazada kanallar mavjud emas."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Add channel ", callback_data="add_channel_start"),
            InlineKeyboardButton(text="➖ Del channel ", callback_data="del_channel_start")
        ],
        [InlineKeyboardButton(text="📢 To'liq ro'yxat", callback_data="full_channel:1")],
        [InlineKeyboardButton(text="🔙 Admin panelga qaytish", callback_data="admin_panel")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
        
    await callback.answer()






#================Channel Add=====================

@router.callback_query(F.data == "add_channel_start")
async def add_channel_start(callback: types.CallbackQuery, state: FSMContext):

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels")]
    ])

    await callback.message.edit_text(
        "🚀 <b>Kanal QO‘SHISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 Format:\n"
        "<code>-100123456789 @kanal_username</code>\n\n"
        "⚠️ Bot kanalga admin bo‘lishi shart!",
        reply_markup=kb,
        parse_mode="HTML"
    )

    await state.set_state(AddChannel.waiting_for_info)
    await callback.answer()




#====================================

# 1. Faqat -100 bilan boshlangan xabarlarni qabul qiluvchi handler
@router.message(AddChannel.waiting_for_info, F.text.startswith("-100"))
async def check_channel_info(message: types.Message, state: FSMContext, bot: Bot):
    try:
        parts = message.text.split()

        if len(parts) < 2:
            return await message.answer("❌ Namuna: <code>-100... @username</code>")

        c_id, c_link = parts[0], parts[1]

        if not c_link.startswith("@"):
            return await message.answer("❌ Username @ bilan boshlanishi kerak!")

        # BOT ADMIN CHECK
        member = await bot.get_chat_member(c_id, bot.id)
        if member.status not in ("administrator", "creator"):
            return await message.answer("❌ Bot kanalga admin emas!")

        chat = await bot.get_chat(c_id)

        await state.update_data(
            c_id=c_id,
            c_title=chat.title,
            c_link=c_link
        )

        text = (
            "✅ <b>KANAL TOPILDI!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Nomi:</b> {chat.title}\n"
            f"<b>ID:</b> <code>{c_id}</code>\n"
            f"<b>Username:</b> {c_link}\n\n"
            "Tasdiqlaysizmi?"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_add_channel")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels")]
        ])

        await message.answer(text, reply_markup=kb, parse_mode="HTML")

    except Exception as e:
        await message.answer(
            "❌ Xatolik!\nBot kanalga kira olmadi yoki ID noto‘g‘ri."
        )

#====================================

# 2. Agar foydalanuvchi state ichida bo'lsa-yu, lekin boshqa narsa yozsa (123v kabi)
@router.message(AddChannel.waiting_for_info)
async def invalid_channel_format(message: types.Message):
    await message.answer(
        "⚠️ <b>Noto'g'ri format!</b>\n\n"
        "Iltimos, kanal ID raqamini (<b>-100</b> bilan boshlanadigan) va username yuboring.\n"
        "Misol: <code>-100123456789 @kanal_user</code>\n\n"
        "<i>Bekor qilish uchun /cancel buyrug'ini yuboring.</i>",
        parse_mode="HTML"
    )



#====================================

@router.callback_query(F.data == "confirm_add_channel")
async def confirm_add_channel(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    # 1. Middleware xavfsizligi (Olmos middleware None qaytarsa)
    if session is None:
        return await callback.answer("⚠️ Baza ulanishida xatolik. Keyinroq urunib ko'ring.", show_alert=True)

    data = await state.get_data()

    if not all(k in data for k in ("c_id", "c_title", "c_link")):
        await state.clear()
        return await callback.answer("⚠️ Ma'lumotlar eskirgan.", show_alert=True)

    try:
        # 2. Postgres xavfsizligi: IDni aniq integerga o'tkazamiz
        # Bu 'bigint = character varying' xatosini yo'qotadi
        target_channel_id = int(data['c_id'])

        # DUPLICATE CHECK
        existing = await session.execute(
            select(Channel).where(Channel.channel_id == target_channel_id)
        )

        if existing.scalar():
            await state.clear()
            return await callback.answer("⚠️ Bu kanal allaqachon mavjud!", show_alert=True)

        # URL FIX
        raw_link = str(data['c_link'])
        if raw_link.startswith("http"):
            final_url = raw_link
        else:
            final_url = f"https://t.me/{raw_link.replace('@','')}"

        # 3. Model yaratishda ham integer ID ishlatamiz
        new_ch = Channel(
            channel_id=target_channel_id,
            title=data['c_title'],
            url=final_url,
            is_active=True
        )
        
        session.add(new_ch)
        await session.commit()
        await state.clear()

        await callback.message.edit_text(
            "🎉 <b>Muvaffaqiyatli qo‘shildi!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 <b>{data['c_title']}</b> kanal tizimga qo‘shildi.",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="📢 Kanallar bo‘limiga qaytish", callback_data="admin_channels")]
            ]),
            parse_mode="HTML"
        )

    except ValueError:
        await callback.answer("❌ Kanal ID formati noto'g'ri!", show_alert=True)
    except Exception as e:
        if session:
            await session.rollback()
        logging.error(f"Kanal qo‘shishda xatolik: {e}")
        await callback.answer("❌ Saqlashda xatolik yuz berdi!", show_alert=True)

    await callback.answer()




#================Channel Full=====================

@router.callback_query(F.data.startswith("full_channel"))
async def show_all_channels(callback: types.CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    
    # Callback data'dan sahifa raqamini olamiz, agar bo'lmasa 1-sahifa
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1
    limit = 5 # Har bir sahifada 5 ta kanal

    # Bazadan barcha kanallarni olish
    result = await session.execute(select(Channel).order_by(Channel.id))
    channels = result.scalars().all()

    if not channels:
        return await callback.answer("⚠️ Hozircha hech qanday kanal qo'shilmagan.", show_alert=True)

    # Umumiy sahifalar sonini hisoblash
    total_pages = (len(channels) + limit - 1) // limit
    current_page_data = paginate(channels, page, limit)

    keyboard = []
    
    # Kanallar tugmalari
    for ch in current_page_data:
        status_emoji = "✅" if ch.is_active else "❌"
        keyboard.append([InlineKeyboardButton(text=f"{status_emoji} {ch.title}", callback_data=f"info_ch_{ch.channel_id}:{page}")])

    # Navigatsiya tugmalari (Oldingi, Sahifa raqami, Keyingi)
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"full_channel:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="ignore"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"full_channel:{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    # Orqaga qaytish tugmasi (Asosiy admin kanallar menyusiga)
    keyboard.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    text = (
        "📋 <b>BARCHA KANALLAR RO'YXATI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Batafsil ma'lumot olish uchun kanal ustiga bosing:\n"
        f"<i>Jami kanallar: {len(channels)} ta</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception: # Agar xabar o'zgarmagan bo'lsa xato bermasligi uchun
        pass
    
    await callback.answer()



from html import escape







#====================================

@router.callback_query(F.data.startswith("info_ch_"))
async def channel_info_detail(callback: types.CallbackQuery, session: AsyncSession):
    if session is None:
        return await callback.answer("⚠️ Ma'lumotlar bazasi bilan aloqa yo'q!", show_alert=True)

    # 1. Toza Parsing
    try:
        # info_ch_123:1 -> ch_id=123, current_page=1
        data_part = callback.data.replace("info_ch_", "")
        parts = data_part.split(":")
        ch_id = int(parts[0])
        current_page = int(parts[1]) if len(parts) > 1 else 1
    except (ValueError, IndexError):
        return await callback.answer("❌ Noto'g'ri ma'lumot formati!", show_alert=True)

    try:
        # 2. Kanalni olish
        result = await session.execute(select(Channel).where(Channel.channel_id == ch_id))
        channel = result.scalar_one_or_none()

        if not channel:
            return await callback.answer("❌ Kanal ma'lumotlar bazasidan topilmadi!", show_alert=True)

        # 3. Foydalanuvchilar sonini hisoblash (Optimallashtirilgan)
        # referred_by_channel ustunining tipiga qarab ch_id ni o'giring
        user_count_stmt = select(func.count()).where(DBUser.referred_by_channel == str(ch_id))
        user_count = await session.scalar(user_count_stmt) or 0

        # 4. Matn tayyorlash
        status_emoji = "✅ Faol" if channel.is_active else "❌ O'chirilgan"
        created = channel.created_at.strftime('%d.%m.%Y %H:%M') if channel.created_at else "Noma'lum"
        
        text = (
            f"📊 <b>Kanal statistikasi:</b>\n"
            f"🔹 <b>Nomi:</b> {escape(channel.title)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 <b>ID:</b> <code>{channel.channel_id}</code>\n"
            f"🔗 <b>Havola:</b> {channel.url}\n"
            f"👥 <b>Yo‘naltirilganlar:</b> <code>{user_count}</code> ta\n"
            f"⚙️ <b>Holati:</b> {status_emoji}\n"
            f"📅 <b>Qo'shilgan vaqti:</b> {created}\n"
        )

    
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
           
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"full_channel:{current_page}")]
        ])

        await callback.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        logging.error(f"Channel Info Detail Error: {e}")
        return await callback.answer("❌ Ma'lumotlarni yuklashda texnik xatolik!", show_alert=True)

    await callback.answer()



#================Channel Del=====================
@router.callback_query(F.data.startswith("del_channel_start"))
async def del_channel_start(callback: types.CallbackQuery, session: AsyncSession):
    try:
        # 1. safe page parse
        raw = callback.data.split(":")
        page = int(raw[1]) if len(raw) > 1 and raw[1].isdigit() else 1
        limit = 5

        # 2. DB
        result = await session.execute(
            select(Channel).order_by(Channel.created_at.desc())
        )
        channels = result.scalars().all()

        if not channels:
            return await callback.answer(
                "⚠️ O'chirish uchun kanallar mavjud emas!",
                show_alert=True
            )

        # 3. pagination
        total_channels = len(channels)
        total_pages = max((total_channels + limit - 1) // limit, 1)

        page = max(1, min(page, total_pages))

        start = (page - 1) * limit
        end = start + limit
        current_page_data = channels[start:end]

        # 4. keyboard
        keyboard = []

        for ch in current_page_data:
            title = getattr(ch, "title", "No title")
            status_emoji = "✅" if ch.is_active else "❌"

            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑 {status_emoji} {title[:20]}",
                    callback_data=f"del_ch_{ch.channel_id}:{page}"
                )
            ])

        # 5. nav
        nav = []

        if page > 1:
            nav.append(
                InlineKeyboardButton(
                    text="⬅️ Oldingi",
                    callback_data=f"del_channel_start:{page-1}"
                )
            )

        nav.append(
            InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data="noop"
            )
        )

        if page < total_pages:
            nav.append(
                InlineKeyboardButton(
                    text="Keyingi ➡️",
                    callback_data=f"del_channel_start:{page+1}"
                )
            )

        keyboard.append(nav)

        # 6. back
        keyboard.append([
            InlineKeyboardButton(
                text="🔙 Orqaga",
                callback_data="admin_channels"
            )
        ])

        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

        text = (
            "🗑 <b>KANAL O'CHIRISH BO'LIMI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "O'chirmoqchi bo'lgan kanalingiz ustiga bosing:\n\n"
            f"<i>Jami kanallar: {total_channels} ta</i>"
        )

        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        print("del_channel_start error:", e)
        try:
            await callback.answer("⚠️ Xatolik yuz berdi", show_alert=True)
        except:
            pass





#====================================

@router.callback_query(F.data.startswith("del_ch_"))
async def delete_confirm(callback: types.CallbackQuery, session: AsyncSession):
    try:
        # safe parse
        raw = callback.data.replace("del_ch_", "")
        parts = raw.split(":")

        if not parts[0].isdigit():
            return await callback.answer("⚠️ Noto‘g‘ri ma’lumot", show_alert=True)

        ch_id = int(parts[0])
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1

        # DB
        channel = await session.get(Channel, ch_id)

        if not channel:
            return await callback.answer("❌ Kanal topilmadi!", show_alert=True)

        title = getattr(channel, "title", "Noma'lum")

        text = (
            f"❓ <b>Haqiqatdan ham ushbu kanalni o'chirmoqchimisiz?</b>\n\n"
            f"🔸 Kanal: <b>{title}</b>\n"
            f"🆔 ID: <code>{ch_id}</code>\n"
            f"📄 Sahifa: {page}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"confirm_del_{ch_id}:{page}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=f"del_channel_start:{page}"
                )
            ]
        ])

        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        print("delete_confirm error:", e)
        await callback.answer("⚠️ Xatolik yuz berdi", show_alert=True)





#================got ot====================

@router.callback_query(F.data.startswith("go_to_channel:"))
async def track_channel_redirect(callback: types.CallbackQuery, session: AsyncSession):

    try:
        _, ch_id = callback.data.split(":")
        ch_id = int(ch_id)
    except (ValueError, IndexError):
        return await callback.answer("❌ Xato callback!", show_alert=True)

    user_id = callback.from_user.id

    # DB update (optional tracking)
    await session.execute(
        update(DBUser)
        .where(DBUser.user_id == user_id)
        .values(last_redirected_channel=str(ch_id))
    )
    await session.commit()

    # Channel olish
    result = await session.execute(
        select(Channel).where(Channel.channel_id == ch_id)
    )
    channel = result.scalar_one_or_none()

    if not channel:
        return await callback.answer("❌ Kanal topilmadi!", show_alert=True)

    text = (
        "📢 <b>Kanalga obuna bo‘ling</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Kanalga o‘ting\n"
        "2️⃣ Obuna bo‘ling\n"
        "3️⃣ 'Tasdiqlash' tugmasini bosing"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📢 Kanalga o‘tish", url=channel.url)],
        [types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"check_sub:{ch_id}")]
    ])

    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()