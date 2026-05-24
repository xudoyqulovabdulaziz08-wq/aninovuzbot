import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import anime_menu_kb


router = Router(name="vip_menu_router")
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


#==============================anime_menu================================#
#========================================================================#