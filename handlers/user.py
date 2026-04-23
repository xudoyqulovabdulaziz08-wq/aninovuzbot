


from aiogram import Router, F, types
from database.models import DBUser
router = Router()


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


