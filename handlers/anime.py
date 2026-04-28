# handlers/anime.py

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


# bu yerda qidiruv natijalarini ko'rsatish va reyting berish funksiyalarini qo'shish mumkin.
# tez oerda ishga tushadi...
# sabab bot hozircha faqat ishga tushish bosqichida va bu bo'lim hali tayyor emas.