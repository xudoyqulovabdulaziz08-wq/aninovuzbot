import pytz
import logging
from datetime import datetime, timezone
from typing import Any, Union 
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from database.repository import UserRepository
from keyboards.inline import vip_buy_kb, cabinet_kb

router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')




#==========================👤 Shaxsiy kabinet============================#
#========================================================================#
@router.message(F.text == "👤 Shaxsiy kabinet")
@router.callback_query(F.data == "cabinet")
async def personal_cabinet(event: Union[types.Message, types.CallbackQuery], **data):
    user_id = event.from_user.id
    # Middleware'dan kelgan 'user' ni xavfsiz olish
    user = data.get("user") or {}
    state = data.get("state")
    await state.clear()
    
    is_cb = isinstance(event, types.CallbackQuery)
    message = event.message if is_cb else event

    # 1. STATUS MANTIQI (Creator, Admin, VIP, User)
    
    
    raw_status = user.get("status", "user")
    is_vip = user.get("is_vip", False)

    if int(user_id) == int(CREATOR_ID):
        status_label = "👑 CREATOR"
    elif raw_status == "admin":
        status_label = "🛡 ADMIN"
    elif is_vip:
        status_label = "💎 VIP"
    else:
        status_label = "👤 USER"

    # 2. TIMEZONE & VIP LOGIC (Siz yozgan qism)
    # 2. TIMEZONE & VIP LOGIC (Kesh formatiga moslangan)
    uzb_tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(timezone.utc)
    
    vip_expire_ts = user.get("vip_expire_date") # Keshdan timestamp keladi
    
    if vip_expire_ts:
        ve_dt = datetime.fromtimestamp(vip_expire_ts, tz=timezone.utc)
        if ve_dt > now:
            ve_local = ve_dt.astimezone(uzb_tz)
            vip_status = f"✅ Faol ({ve_local.strftime('%d.%m.%Y | %H:%M')})"
        else:
            vip_status = "⚠️ Muddati tugagan"
    else:
        vip_status = "❌ Faol emas"

    
    text = (
        "👤 <b>SHAXSIY KABINET</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🏅 Status: <b>{status_label}</b>\n"
        f"⭐ Ballaringiz: <b>{user.get('points', 0)}</b>\n"
        f"👥 Takliflar: <b>{user.get('referral_count', 0)} ta</b>\n"
        f"💎 VIP holati: <b>{vip_status}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    kb= cabinet_kb()
    # 4. XAVFSIZ JAVOB BERISH
    if is_cb:
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise e
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        