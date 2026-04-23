from datetime import datetime
from aiogram import types, F, Router
from sqlalchemy import select, desc
from database.models import DBUser
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()


# ================= TUGMA HANDLERLARI =================
@router.message(F.text == "🔍 Anime qidirish")
async def anime_search(message: types.Message):
    await message.answer("🔍 Qidirmoqchi bo'lgan anime nomini yozing:")


@router.message(F.text == "👤 Shaxsiy kabinet")
async def personal_cabinet(message: types.Message, user: DBUser):
    now = datetime.now()
    vip_status = "❌ Faol emas"
    
    if user.vip_expire_date:
        if user.vip_expire_date > now:
            vip_status = f"✅ {user.vip_expire_date.strftime('%d.%m.%Y')} gacha"
        else:
            vip_status = "⚠️ Muddati tugagan"

    text = (
        f"👤 <b>Shaxsiy kabinet</b>\n\n"
        f"🆔 ID: <code>{user.user_id}</code>\n"
        f"👤 Username: @{user.username or 'Yo\'q'}\n"
        f"🏅 Status: <b>{user.status.upper()}</b>\n"
        f"⭐ Ballar: <b>{user.points}</b>\n"
        f"👥 Takliflar: <b>{user.referral_count}</b>\n"
        f"💎 VIP: <b>{vip_status}</b>"
    )
    await message.answer(text)


@router.message(F.text == "🌟 Reyting")
async def rating(message: types.Message, session: AsyncSession):
    # 1. Bazadan ballar bo'yicha TOP 10 foydalanuvchini olamiz
    stmt = select(DBUser).order_by(desc(DBUser.points)).limit(10)
    result = await session.execute(stmt)
    top_users = result.scalars().all()

    if not top_users:
        return await message.answer("📭 Reyting hozircha bo'sh.")

    text = "🏆 <b>TOP-10 Foydalanuvchilar:</b>\n\n"
    
    for i, top_user in enumerate(top_users, 1):
        # Username bo'lsa username, bo'lmasa ID ni ko'rsatamiz
        user_name = f"@{top_user.username}" if top_user.username else f"ID:{top_user.user_id}"
        
        # Har xil o'rinlar uchun medallar
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👤"
        
        text += f"{medal} {i}. {user_name} — <b>{top_user.points} ball</b>\n"

    text += f"\n\nSizning ballaringiz: <b>{getattr(message, 'user_points', 'Noma\'lum')}</b>" # Middleware orqali ballni ham yuborsa bo'ladi
    await message.answer(text)


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


