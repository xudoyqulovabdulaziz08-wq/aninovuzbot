from datetime import datetime
from aiogram import types, F, Router
from sqlalchemy import select, desc
from database.models import DBUser


router = Router()


@property
def average_rating(self):
    if self.rating_count > 0:
        return round(float(self.rating_sum) / self.rating_count, 1)
    return 0.0

@router.message(F.text == "🔍 Anime qidirish")
async def anime_search(message: types.Message):
    await message.answer("🔍 Qidirmoqchi bo'lgan anime nomini yozing:")