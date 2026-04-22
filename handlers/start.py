from aiogram import Router, types, Bot, F
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import DBUser

router = Router()

# Kanallar ro'yxati: ["@kanal1", "@kanal2"] shaklida to'ldiring
CHANNELS = []


async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Foydalanuvchi barcha kanallarga obuna bo'lganini tekshiradi."""
    if not CHANNELS:
        return True
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            return False
    return True


def get_sub_keyboard() -> types.InlineKeyboardMarkup:
    """Obuna tugmalar klaviaturasi."""
    buttons = [
        [types.InlineKeyboardButton(text=f"📢 Kanal {i+1}", url=f"https://t.me/{ch.lstrip('@')}")]
        for i, ch in enumerate(CHANNELS)
    ]
    buttons.append([types.InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def get_main_menu(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    """Asosiy menyu klaviaturasi."""
    kb = [
        [types.KeyboardButton(text="🔍 Anime qidirish"), types.KeyboardButton(text="👤 Shaxsiy kabinet")],
        [types.KeyboardButton(text="🌟 Reyting"), types.KeyboardButton(text="❓ Qo'llanma")],
        [types.KeyboardButton(text="💎 VIP sotib olish"), types.KeyboardButton(text="📢 Reklama berish")]
    ]
    if is_admin:
        kb.append([types.KeyboardButton(text="⚙️ SC ADMIN PANEL")])
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Bo'limni tanlang...")


# ================= /start =================
@router.message(CommandStart())
async def cmd_start(message: types.Message, user: DBUser, session: AsyncSession, bot: Bot):
    if user.status not in ["admin", "vip"]:
        if not await check_subscription(bot, message.from_user.id):
            return await message.answer(
                "⚠️ Botdan foydalanish uchun kanallarimizga obuna bo'ling:",
                reply_markup=get_sub_keyboard()
            )

    await message.answer(
        f"Xush kelibsiz, <b>{message.from_user.full_name}</b>!\n"
        f"Statusingiz: <b>{user.status}</b>",
        reply_markup=get_main_menu(is_admin=(user.status == "admin"))
    )


# ✅ YANGI: "Tekshirish" tugmasi bosilganda
@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery, user: DBUser, bot: Bot):
    is_subscribed = await check_subscription(bot, callback.from_user.id)

    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer(
            f"✅ Rahmat! Xush kelibsiz, <b>{callback.from_user.full_name}</b>!\n"
            f"Statusingiz: <b>{user.status}</b>",
            reply_markup=get_main_menu(is_admin=(user.status == "admin"))
        )
    else:
        await callback.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)


# ================= TUGMA HANDLERLARI =================
@router.message(F.text == "🔍 Anime qidirish")
async def anime_search(message: types.Message):
    await message.answer("🔍 Qidirmoqchi bo'lgan anime nomini yozing:")


@router.message(F.text == "👤 Shaxsiy kabinet")
async def personal_cabinet(message: types.Message, user: DBUser):
    from datetime import datetime
    vip_info = ""
    if user.vip_expire_date:
        if user.vip_expire_date > datetime.now():
            vip_info = f"\n💎 VIP: <b>{user.vip_expire_date.strftime('%d.%m.%Y')}</b> gacha"
        else:
            vip_info = "\n💎 VIP: <b>Muddati o'tgan</b>"

    text = (
        f"👤 <b>Shaxsiy kabinet</b>\n\n"
        f"🆔 ID: <code>{user.user_id}</code>\n"
        f"👤 Username: @{user.username or 'Yo\'q'}\n"
        f"🏅 Status: <b>{user.status}</b>\n"
        f"⭐ Ballar: <b>{user.points}</b>\n"
        f"👥 Taklif qilinganlar: <b>{user.referral_count}</b>"
        f"{vip_info}"
    )
    await message.answer(text)


@router.message(F.text == "🌟 Reyting")
async def rating(message: types.Message):
    await message.answer("🌟 <b>Reyting</b>\n\nTez kunda...")


@router.message(F.text == "❓ Qo'llanma")
async def help_page(message: types.Message):
    text = (
        "❓ <b>Qo'llanma</b>\n\n"
        "🔍 <b>Anime qidirish</b> — anime nomini yozing\n"
        "👤 <b>Shaxsiy kabinet</b> — profilingizni ko'ring\n"
        "🌟 <b>Reyting</b> — eng mashhur animalar\n"
        "💎 <b>VIP</b> — maxsus imkoniyatlar\n\n"
        "Savollar uchun: @admin"
    )
    await message.answer(text)


@router.message(F.text == "💎 VIP sotib olish")
async def buy_vip(message: types.Message):
    await message.answer(
        "💎 <b>VIP rejim</b>\n\n"
        "✅ Reklamasiz ko'rish\n"
        "✅ Barcha kanallar\n"
        "✅ Maxsus kontentlar\n\n"
        "Tez kunda..."
    )


@router.message(F.text == "📢 Reklama berish")
async def advertisement(message: types.Message):
    await message.answer("📢 Reklama uchun: @admin")


@router.message(F.text == "⚙️ SC ADMIN PANEL")
async def admin_panel(message: types.Message, user: DBUser):
    if user.status != "admin":
        return await message.answer("❌ Ruxsat yo'q!")
    await message.answer("⚙️ <b>Admin panel</b>\n\nTez kunda...")