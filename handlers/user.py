from datetime import datetime
from aiogram import types, F, Router
from sqlalchemy import select, desc
from database.models import DBUser
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()





@router.message(F.text == "👤 Shaxsiy kabinet")
async def personal_cabinet(message: types.Message, user: DBUser):
    now = datetime.now()
    vip_status = "❌ Faol emas"
    
    # VIP muddatini tekshirish
    if user.vip_expire_date:
        if user.vip_expire_date > now:
            vip_status = f"✅ {user.vip_expire_date.strftime('%d.%m.%Y')} gacha"
        else:
            vip_status = "⚠️ Muddati tugagan"

    # 🚀 MUAMMONI YECHIMI: 
    # Username'ni bazadan emas, hozirgi xabardan olamiz.
    # Agar foydalanuvchida username bo'lmasa "O'rnatilmagan" deb chiqadi.
    current_username = message.from_user.username
    display_username = f"@{current_username}" if current_username else "O'rnatilmagan"

    text = (
        f"👤 <b>Shaxsiy kabinet</b>\n\n"
        f"🆔 ID: <code>{user.user_id}</code>\n"
        f"👤 Username: {display_username}\n"  # Jonli username
        f"🏅 Status: <b>{user.status.upper()}</b>\n"
        f"⭐ Ballar: <b>{user.points}</b>\n"
        f"👥 Takliflar: <b>{user.referral_count}</b>\n"
        f"💎 VIP: <b>{vip_status}</b>"
    )
    await message.answer(text)


@router.message(F.text == "🌟 Reyting")
async def rating(message: types.Message, session: AsyncSession, user: DBUser):
    # 1. Bazadan TOP 10 ni olamiz
    stmt = select(DBUser).order_by(DBUser.points.desc()).limit(10)
    result = await session.execute(stmt)
    top_users = result.scalars().all()

    if not top_users:
        return await message.answer("📭 Reyting hozircha bo'sh.")

    text = "🏆 <b>TOP-10 Foydalanuvchilar:</b>\n\n"
    
    for i, top_user in enumerate(top_users, 1):
        # Username tekshiruvi: Agar bazada @Yo'q bo'lsa, ID ko'rsatiladi
        if top_user.username and top_user.username != "Yo'q":
            user_name = f"@{top_user.username}"
        else:
            user_name = f"ID:<code>{top_user.user_id}</code>"
            
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👤"
        text += f"{medal} {i}. {user_name} — <b>{top_user.points} ball</b>\n"

    # O'z ballingiz (Middleware orqali kelgan obyektni ishlatamiz)
    my_points = user.points if user.points is not None else 0
    text += f"\n\nSizning ballaringiz: <b>{my_points} ball</b>"
    
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
    await message.answer("📢Reklama xizmati tez kunda...")


