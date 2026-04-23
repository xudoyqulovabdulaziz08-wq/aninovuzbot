from datetime import datetime
from aiogram import types, F, Router
from sqlalchemy import select, desc
from database.models import DBUser


router = Router()



@router.message(F.text == "🔍 Anime qidirish")
async def anime_search(message: types.Message):
    await message.answer("🔍 Qidirmoqchi bo'lgan anime nomini yozing:")