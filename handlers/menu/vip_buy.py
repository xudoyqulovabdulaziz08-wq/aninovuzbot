import logging
import html
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from urllib.parse import quote

from config import config
from keyboards.inline import vip_buy_kb, buy_vip_med_kb

router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID', 0)


# ========================================================================
# 💎 1. VIP SOTIB OLISH ASOSIY MENYUSI (MESSAGE & CALLBACK)
# ========================================================================
@router.message(F.text == "💎 VIP sotib olish")
@router.callback_query(F.data == "buy_vip_menu")
async def buy_vip_menu(event: types.Message | types.CallbackQuery, state: FSMContext, **data):
    if state:
        await state.clear()
        
    user = data.get("user") or {}
    user_id = user.get("user_id") or event.from_user.id
    user_status = user.get("status", "user")
    is_vip = user.get("is_vip", False)
    points = user.get("points", 0)

    # Anime rutbalari (Status tekshiruvi)
    if int(user_id) == int(CREATOR_ID):
        status_info = "👑 <b>KAGE (Yaratuvchi)</b>"
    elif user_status == "admin":
        status_info = "🛡 <b>Admin</b>"
    elif is_vip:
        status_info = "💎 <b>VIP </b>"
    else:
        status_info = "👤 <b>Foydalanuvchi</b>"
    
    text = (
    "╔═════════ ⛩ ═════════╗\n"
    "   💎 <b>VIP OLISH</b> 💎\n"
    "╚═════════ ⛩ ═════════╝\n\n"
    
    # 1-Blok: Foydalanuvchi statusi va IDsi
        f"👤 <b>SIZNING PROFILINGIZ:</b>\n"
        f"<blockquote expandable><b>STATUS</b>: {status_info}\n"
        f"<b>ID</b>: <code>{user_id}</code></blockquote>\n"
    
        # 2-Blok: Premium afzalliklari
        f"👑 <b>VIP  AFZALLIKLARI:</b>\n"
        f"<blockquote expandable>🚀 <b>Cheklovlarsiz qidiruv</b> - Hech qanday taymautsiz tezkor qidiruv tizimi. </blockquote>\n"
        f"<blockquote expandable>🚫 <b>Reklamasiz muhit</b> - Botdan mutlaqo reklamasiz va toza foydalanish.</blockquote>\n"
        f"<blockquote expandable>✨ <b>Eksklyuziv status</b> - Profilingizda maxsus VIP ramka va nishonlar.</blockquote>\n"
    
        # 3-Blok: Tarifikatsiya va bonus tizimi
        f"⚖️ <b>BALL ALMASHUVI:</b>\n"
        f"<blockquote expandable>🏷 <code>100 energiya = 30 kun VIP</code></blockquote>\n"
        f"<blockquote expandable><i>To'plagan energiyalaringizni darhol Premium obunaga almashtirishingiz mumkin!</i></blockquote>\n"
    
        f"═════════ ⛩ ═════════\n"
        f"👇 <i>O'z darajangizni oshirish uchun quyidagi tugmalardan birini tanlang:</i>"
    )
    
    kb = vip_buy_kb(is_vip=is_vip)
    
    try:
        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ VIP menyu xatosi: {e}")
    except Exception as e:
        logger.error(f"❌ VIP menyu kutilmagan xatolik: {e}")
    finally:
        if isinstance(event, types.CallbackQuery):
            await event.answer()


# ========================================================================
# 💳 2. VIP NARXLAR VA TARIFLARNI KO'RISH
# ========================================================================
@router.callback_query(F.data == "buy_vip_med")
async def buy_vip_med_handler(callback: types.CallbackQuery, state: FSMContext):
    if state:
        await state.clear()
        
    user_id = callback.from_user.id
    
    VIP_PRICES = {
        "1m": "20000",
        "3m": "55000",
        "6m": "100000",
        "12m": "180000"
    }
    
    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   💳 <b>VIP TARIFLARI</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
    
        f"Salom, <b>{html.escape(callback.from_user.full_name)}</b>! 👋\n\n"
    
        f"👤 <b>TARIF MA'LUMOTLARI:</b>\n"
        f"<blockquote expandable> Maxfiy 🆔: <code>{user_id}</code></blockquote>\n"
        f"<blockquote expandable><i>Sotib olish paytida ushbu ID hisobga olinadi.</i></blockquote>\n\n"
    
        f"💵 <b>Mavjud tariflar va narxlar:</b>\n"
        
        f"<blockquote expandable>🔹 1 oylik ➔ <b>{int(VIP_PRICES['1m']):,} so'm</b></blockquote>\n"
        f"<blockquote expandable>🔹 3 oylik ➔ <b>{int(VIP_PRICES['3m']):,} so'm</b></blockquote>\n"
        f"<blockquote expandable>🔹 6 oylik ➔ <b>{int(VIP_PRICES['6m']):,} so'm</b></blockquote>\n"
        f"<blockquote expandable>🔹 1 yillik ➔ <b>{int(VIP_PRICES['12m']):,} so'm</b></blockquote>\n"
        
    
        f"⚡️ <i>Har bir tarif barcha premium afzalliklarni cheklovsiz faollashtiradi.</i>\n"
        f"═════════ ⛩ ═════════\n"
        f"👇 <i>Sotib olish jarayonini boshlash uchun tarifni tanlang:</i>"
    )
    
    kb = buy_vip_med_kb(user_id=user_id)
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ VIP narxlar menyusi xatosi: {e}")
    finally:
        await callback.answer("💳 Shartnomalar varag'i ochildi")


# ========================================================================
# 🛒 3. TARIFNI TANLASH VA ADMINGA YAZISH
# ========================================================================
@router.callback_query(F.data.startswith("buyer_vip_"))
async def vip_tariff_selection_handler(callback: types.CallbackQuery):
    tariff_code = callback.data.split("_")[2]
    
    tariffs = {
        "1m": {"name": "1 oylik", "price": "20,000"},
        "3m": {"name": "3 oylik", "price": "55,000"},
        "6m": {"name": "6 oylik", "price": "100,000"},
        "12m": {"name": "1 yillik", "price": "180,000"}
    }
    
    data = tariffs.get(tariff_code, {"name": "Noma'lum", "price": "0"})
    user_id = callback.from_user.id
    admin_username = "Khudoyqulov_pg"
    
    raw_msg = f"Assalomu alaykum! {data['name']} muddatga ({data['price']} so'm) VIP xarid qilmoqchiman. Maxfiy ID: {user_id}"
    admin_url = f"https://t.me/{admin_username}?text={quote(raw_msg)}"
    
    text = (
        f"✅ <b>{data['name']} VIP shartnomasi tanlandi!</b>\n\n"
        f"💰 <b>Kerakli summa:</b> {data['price']} so'm\n\n"
        f"Buyuk Kage (Admin) bilan bog'lanib to'lovni amalga oshiring. "
        f"Quyidagi tugmani bossangiz, adminga yozish uchun tayyor xabar ochiladi 💬"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Admin bilan bog'lanish", url=admin_url))
    builder.row(types.InlineKeyboardButton(text="⬅️ Ortga qaytish", callback_data="buy_vip_med"))
    
    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ VIP xarid menyusi xatosi: {e}")
    finally:
        await callback.answer(f"✅ {data['name']} tarifi tanlandi")


# ========================================================================
# 🎁 4. VIP BONUS OLISH (TEZ ORADA)
# ========================================================================
@router.callback_query(F.data == "buy_vip_bonus")
async def buy_vip_bonus_handler(callback: types.CallbackQuery):
    
    text = (
        "╔═════════ ⛩ ═════════╗\n"
        "   🎁 <b>BALL ALMASHTIRISH</b>\n"
        "╚═════════ ⛩ ═════════╝\n\n"
        "Bu bo'lim ustida hali ishlanmoqda! ⏳\n\n"
        "❗️ Hozircha to'plagan ballarni VIP darajaga almashtirish imkoniyati yopiq. "
        "Bot muhandislari bu tizimni tez orada yakunlashadi. Yangilanishlarni kuting! 🌸"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⛩ Ortga qaytish", callback_data="buy_vip_med"))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ VIP bonus xatosi: {e}")
    finally:
        await callback.answer("🎁 Bonus bo'limi tez orada ochiladi")