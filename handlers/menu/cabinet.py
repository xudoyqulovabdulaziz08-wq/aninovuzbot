import pytz
import logging
from datetime import datetime, timezone
from typing import Union

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config import config
from keyboards.inline import cabinet_kb

router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


#==========================👤 Shaxsiy kabinet============================#
#========================================================================#
@router.message(F.text == "👤 Shaxsiy kabinet")
@router.callback_query(F.data == "cabinet")
async def personal_cabinet(event: Union[types.Message, types.CallbackQuery], state: FSMContext, user: dict = None, **data):
    user_id = event.from_user.id
    # Middleware'dan kelgan 'user' ni olish (agar yo'q bo'lsa bo'sh dict)
    user = user or {}
    
    # State tozalash (foydalanuvchi qandaydir jarayonda bo'lsa uni to'xtatadi)
    if state:
        await state.clear()
    
    is_cb = isinstance(event, types.CallbackQuery)
    message = event.message if is_cb else event

    # 1. STATUS MANTIQI (Anime Themed 🎌)
    raw_status = user.get("status", "user")
    is_vip = user.get("is_vip", False)

    if str(user_id) == str(CREATOR_ID):
        status_label = "👑 KAMI (Yaratuvchi)"
    elif raw_status in ["admin", "owner"]:
        status_label = "🛡 HOKAGE (Admin)"
    elif is_vip:
        status_label = "💎 VIP SENSEI"
    else:
        status_label = "🥷 GENIN (Foydalanuvchi)"

    # 2. TIMEZONE & VIP LOGIC (FIXED: Timestamp emas, ISO String)
    uzb_tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(timezone.utc)
    
    # Keshdan ISO formatdagi sana keladi
    vip_expire_iso = user.get("vip_expire_date") 
    
    if vip_expire_iso:
        try:
            # ISO stringni datetime obyektiga aylantiramiz
            ve_dt = datetime.fromisoformat(vip_expire_iso)
            if ve_dt > now:
                ve_local = ve_dt.astimezone(uzb_tz)
                vip_status = f"✅ Faol ({ve_local.strftime('%d.%m.%Y | %H:%M')})"
            else:
                vip_status = "⚠️ Muddati tugagan"
        except ValueError:
            vip_status = "❌ Sana formati xato"
            logger.error(f"Xato VIP sana formati: {vip_expire_iso}")
    else:
        vip_status = "❌ Faol emas"

    # 3. CHIROYLI UX/UI (Anime Style ✨)
    points = user.get('points', 0)
    referrals = user.get('referral_count', 0)

    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🏮 <b>SHAXSIY KABINET</b> 🏮\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        f"🪪 <b>ID raqam:</b> <code>{user_id}</code>\n"
        f"💠 <b>Daraja:</b> <b>{status_label}</b>\n"
        f"✨ <b>Energiya:</b> <b>{points}</b> <i>(Ballar)</i>\n"
        f"👥 <b>Nakama:</b> <b>{referrals} ta</b> <i>(Takliflar)</i>\n"
        f"💎 <b>Premium:</b> <b>{vip_status}</b>\n\n"
        "🌸 <i>O'zingiz yoqtirgan animelarni biz bilan kashf eting!</i>"
    )

    kb = cabinet_kb()

    # 4. XAVFSIZ JAVOB BERISH VA FLICKER (MILTILLASH) NING OLDINI OLISH
    if is_cb:
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise e
        finally:
            # Answer() tugmani "loading" (aylanib turish) holatidan chiqaradi
            await event.answer() 
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")