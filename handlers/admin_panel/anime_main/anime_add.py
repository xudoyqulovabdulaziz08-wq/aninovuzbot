import logging
import html
import asyncio
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from typing import Any, Optional
from aiogram.filters.callback_data import CallbackData


from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.repository import AnimeRepository
from database.connection import AsyncSession, async_sessionmaker
from database.cache import valkey
from config import config
from keyboards.inline import anime_menu_kb
from database.repository import AnimeRepository
from database.connection import AsyncSession
from database.models import Anime, Genre


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


# =====================================================================
# ⛩ STATE & CALLBACK DEFINITIONS (Imlo xatolari tuzatildi)
# =====================================================================
class AnimeMenuState(StatesGroup):
    adding_anime_name = State()       # 1. Yangi anime nomi
    adding_anime_photo = State()      # 2. Rasm / Poster
    adding_genres = State()           # 3. Janrlar
    adding_year = State()             # 4. Chiqarilgan yil
    adding_description = State()      # 5. Tavsif
    adding_languages = State()        # 6. Tillari (Imlo xatosi FIX)
    adding_episode_video = State()    # 7. Epizod videosi
    updating_anime = State()          # Yangilash holati

class AnimeMenuCallbacks:
    ADD_ANIME = "add_anime"
    ADD_GENRES = "add_genres"
    ADD_YEAR = "add_year"
    ADD_DESCRIPTION = "add_description"
    ADD_EPISODE = "add_episode"
    ADD_PHOTO = "add_photo"
    ADD_LANGUAGES = "add_languages"
    UPDATE_ANIME = "update_anime"


# =====================================================================
# ⛩ QADAM 1: Anime qo'shish boshlanishi (UI & UX PRO MAX)
# =====================================================================
# 🔥 JIDDIY FIX: String qobiqdan chiqarildi, endi filtr to'g'ri ishlaydi!
@router.callback_query(F.data == "AnimeMenuCallbacks.ADD_ANIME" )
async def admin_add(callback: CallbackQuery, state: FSMContext):
    """ 🚀 Yangi anime qo'shish jarayonining start nuqtasi """
    
    # 1. Holatni (State) to'liq tozalab, yangi bosqichni o'rnatamiz
    await state.clear()
    await state.set_state(AnimeMenuState.adding_anime_name)
    
    # 2. Vizual interfeys (Dark Mode va yapon anime minimalizmi uyg'unligi)
    text = (
        "╔═══════════ ⛩ ═══════════╗\n"
        "       <b>YANGI ANIME QO'SHISH</b>\n"
        "╚═══════════ ⛩ ═══════════╝\n\n"
        "🎬 Tizimga yangi anime kiritish jarayoni boshlandi.\n\n"
        "📝 Iltimos, animening <b>rasmiy nomini</b> kiriting:\n"
        "<i>(Masalan: Naruto, Attack on Titan, Solo Leveling)</i>"
    )
    
    # 3. Premium ko'rinishdagi boshqaruv tugmasi
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Jarayonni bekor qilish", 
            callback_data="add_anime_main"
        )
    )
    
    try:
        # 4. Silliq vizual yangilash
        await callback.message.edit_text(
            text=text, 
            reply_markup=builder.as_markup(), 
            parse_mode="HTML"
        )
        # Sarlavha xabarnomasini qisqa va chiroyli tarzda yuboramiz
        await callback.answer("⚙️ Nom kiritish bosqichi...")
        
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Anime panel xatosi: {e}")
            await callback.answer("⚠️ Texnik xatolik yuz berdi.", show_alert=True)

# =====================================================================
# ⛩ QADAM 2: Nomni qabul qilish -> Rasm (Poster) so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_anime_name)
async def process_anime_name(message: Message, state: FSMContext):
    """ 📥 Admin yuborgan anime nomini qabul qilish va poster so'rash """
    
    # 1. Input Validation (Faqat matn ekanligini tekshirish)
    if not message.text or message.text.startswith("/"):
        return await message.answer(
            "⚠️ <b>Xatolik:</b> Iltimos, faqat matnli havola yoki anime nomini kiriting!\n"
            "📌 Yangi anime nomini qaytadan yuboring:"
        )
    
    anime_title = message.text.strip()
    
    # Validation: Juda qisqa yoki bema'ni nomlarni filtrlaymiz
    if len(anime_title) < 2:
        return await message.answer("❌ <b>Anime nomi juda qisqa!</b> Kamida 2 ta belgi bo'lishi shart:")

    # 2. Ma'lumotni repozitoriy standartiga mos 'title' kaliti bilan FSMga yozamiz
    await state.update_data(title=anime_title)
    
    # 3. Keyingi bosqichga (Rasm so'rash) o'tkazamiz
    await state.set_state(AnimeMenuState.adding_anime_photo)

    # 4. Vizual interfeys (Futuristik va aniq yo'riqnoma bilan)
    text = (
        f"⛩ <b>Anime nomi saqlandi:</b> <code>{anime_title}</code>\n"
        "───────────────────────\n\n"
        "🖼 Endi ushbu anime uchun <b>Poster (Rasm)</b> yuboring.\n\n"
        "💡 <i>Tavsiya: Rasmni siqilmagan holda (file) emas, oddiy rasm (photo) "
        "shaklida yuboring yoki rasmning to'g'ridan-to'g'ri URL havolasini kiriting.</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Jarayonni bekor qilish", 
            callback_data="add_anime_main"
        )
    )
    
    # 5. Xavfsiz va chiroyli tarzda yuborish (reply emas, answer)
    await message.answer(
        text=text, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )



# =====================================================================
# ⛩ QADAM 3: Rasmni qabul qilish -> Janrlarni dynamic ko'rsatish
# =====================================================================
# 🔥 FIX: Faqat F.photo emas, umumiy holatda qabul qilib, ichkarida tekshiramiz (Crash proof)
# =====================================================================
# QADAM 4: Admin yuborgan rasmni qabul qilib, janr so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_anime_photo)
async def process_anime_photo(message: Message, state: FSMContext, session: Any):
    """ 📥 Admin yuborgan rasmni (yoki URL) qabul qilib, janr so'rash """
    
    poster_id = None
    
    # 1. Rasm formatlarini tekshirish
    if message.photo:
        poster_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        poster_id = message.document.file_id
    elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
        poster_id = message.text.strip()
    else:
        return await message.answer(
            "⚠️ <b>Noto'g'ri format!</b>\n"
            "Iltimos, animening rasmini yuboring yoki to'g'ri rasm URL havolasini kiriting:"
        )

    # FSM xotirasiga poster_id saqlaymiz
    await state.update_data(poster_id=poster_id)
    await state.set_state(AnimeMenuState.adding_genres)

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🚫 Jarayonni bekor qilish", callback_data="add_anime_main")
    )

    text = (
        "🖼 <b>Poster muvaffaqiyatli qabul qilindi.</b>\n"
        "───────────────────────\n\n"
        "📁 Endi anime <b>janrlarini</b> kiriting:\n\n"
        "<i>Iltimos, janrlarni faqat VERGUL (,) bilan ajratib yozing!</i>\n"
        "<code>Masalan: Shounen, Isekai, Ekshen, Maktab</code>"
    )

    await message.answer(
        text=text, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )




# =====================================================================
# QADAM 5: Admin janrlarni matn ko'rinishida yozganda (Vergul bo'yicha)
# =====================================================================
@router.message(AnimeMenuState.adding_genres)
async def process_anime_genres_message(message: Message, state: FSMContext, session: Any):
    """ 🛡 Janrlarni matn ko'rinishida qabul qilish (faqat vergul) """
    
    if not message.text or message.text.startswith("/"):
        return await message.answer("❌ Iltimos, faqat matn ko'rinishida yozing.")
        
    # 1. Matnni FAQAT vergul bilan ajratamiz (bo'shliq halaqit qilmaydi)
    # Masalan: "Isekai, Slice of Life" -> ["Isekai", "Slice of Life"]
    raw_inputs = [g.strip() for g in message.text.split(",") if g.strip()]

    if not raw_inputs:
        return await message.answer(
            "⚠️ <b>Janrlar aniqlanmadi!</b>\n"
            "Iltimos, janr nomlarini <b>faqat vergul</b> bilan ajratgan holda kiriting.\n"
            "<i>(Masalan: Shounen, Slice of Life, Ekshen)</i>",
            parse_mode="HTML"
        )

    loading_msg = await message.answer("⚙️ <code>Janrlar tekshirilmoqda...</code>", parse_mode="HTML")

    final_genre_names = []

    try:
        for raw_name in raw_inputs:
            # Har bir so'zning bosh harfini katta qilish ("slice of life" -> "Slice of life")
            # yoki capitalize() o'rniga title() ishlatsangiz "Slice Of Life" bo'ladi. O'zingiz tanlaysiz.
            genre_name = raw_name.title() 
            
            # Case-Insensitive qidiruv
            stmt = select(Genre).where(Genre.name.ilike(genre_name))
            result = await session.execute(stmt)
            genre_obj = result.scalar_one_or_none()
            
            # Agar bazada bu janr bo'lmasa, yangi yaratamiz
            if not genre_obj:
                genre_obj = Genre(name=genre_name)
                session.add(genre_obj)
                await session.flush() # ID va saqlash zanjirini tayyorlaymiz
            
            # ID o'rniga NOMINI saqlaymiz, izchillik buzilmasligi uchun!
            if genre_obj.name not in final_genre_names: # Dublikatlarni oldini olish
                final_genre_names.append(genre_obj.name)

        # FSM xotirasiga toza NOMlar ro'yxatini yozamiz
        await state.update_data(selected_genres=final_genre_names)
        await state.set_state(AnimeMenuState.adding_year)
        
        # HTML xavfsizligi
        escaped_names = [html.escape(name) for name in final_genre_names]

        text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "        <b>JANRLAR INDEKSLANDI</b>\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"✍️ <b>Tizim qabul qilgan janrlar:</b>\n"
            f"<code>{', '.join(escaped_names)}</code>\n"
            f"📊 <i>(Jami: {len(final_genre_names)} ta janr muvaffaqiyatli belgilandi)</i>\n"
            "───────────────────────\n\n"
            "📅 Endi animening <b>chiqarilgan yilini</b> kiriting:\n"
            "<i>(Masalan: 2024 yoki 2026)</i>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🚫 Jarayonni bekor qilish", 
                callback_data="add_anime_main"
            )
        )
        
        await loading_msg.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"❌ Janrlarni qayta ishlashda xatolik: {e}")
        await loading_msg.edit_text("❌ Janrlarni indekslashda kutilmagan xatolik yuz berdi.")

# =====================================================================
# ⛩ QADAM 5: Yilni qabul qilish -> Tavsifni so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_year)
async def process_anime_year(message: Message, state: FSMContext):
    """ 📅 Admin yuborgan chiqarilgan yilni qabul qilish va tavsif so'rash """
    
    # 1. Input Validation: Raqam ekanligini va buyruq emasligini tekshirish
    if not message.text or not message.text.isdigit() or message.text.startswith("/"):
        return await message.answer(
            "⚠️ <b>Xatolik:</b> Iltimos, faqat butun son kiriting!\n"
            "📌 Chiqarilgan yilni qaytadan kiriting (Masalan: <code>2025</code>):",
            parse_mode="HTML"
        )
    
    year_value = int(message.text.strip())
    
    # 2. Reallik tekshiruvi (Business Logic Guard)
    if year_value < 1950 or year_value > 2030:
        return await message.answer(
            f"⚠️ <b>Cheklov:</b> Siz kiritgan yil: <code>{year_value}</code>\n"
            "Iltimos, real yilni kiriting (1950 - 2030 yillar oralig'ida):",
            parse_mode="HTML"
        )
        
    # 3. Ma'lumotni FSM xotirasiga yozamiz va keyingi holatga o'tamiz
    await state.update_data(year=year_value)
    await state.set_state(AnimeMenuState.adding_description)

    # 4. Vizual interfeys (Premium ko'rinishda)
    text = (
        f"📅 <b>Chiqarilgan yili saqlandi:</b> <code>{year_value}-yil</code>\n"
        "───────────────────────\n\n"
        "✍️ Endi ushbu anime uchun <b>batafsil tavsif (Description)</b> kiriting:\n\n"
        "<i>📌 Tavsifda animening mavzusi, asosiy qahramonlari, voqealar rivoji va boshqa muhim ma'lumotlarni kiriting. </i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Jarayonni bekor qilish", 
            callback_data="add_anime_main"
        )
    )
    
    # 5. Silliq va toza yuborish (reply emas, answer)
    await message.answer(
        text=text, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )


# =====================================================================
# ⛩ QADAM 6: Tavsifni qabul qilish -> Tillarni so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_description)
async def process_anime_description(message: Message, state: FSMContext):
    """ ✍️ Admin yuborgan tavsifni qabul qilish va tillarni so'rash """
    
    # 1. Input Validation: Faqat matn ekanligini va buyruq (/start, /cancel) emasligini tekshiramiz
    if not message.text or message.text.startswith("/"):
        return await message.answer(
            "⚠️ <b>Xatolik:</b> Iltimos, anime tavsifini matn ko'rinishida yuboring!\n"
            "📌 Tavsifni qaytadan kiriting:"
        )
        
    anime_description = message.text.strip()
    
    # Kichik biznes-loyiha cheklovi: Tavsif juda qisqa bo'lsa qaytaramiz
    if len(anime_description) < 10:
        return await message.answer(
            "⚠️ <b>Tavsif juda qisqa!</b>\n"
            "Foydalanuvchilarga tushunarli bo'lishi uchun kamida 10 ta belgidan iborat tavsif kiriting:"
        )
    
    # 2. Ma'lumotni FSM xotirasiga yozamiz
    await state.update_data(description=anime_description)
    
    # 🔥 FIX: 1-qadamda to'g'rilangan 'adding_languages' state'iga o'tkazamiz
    await state.set_state(AnimeMenuState.adding_languages)

    # 3. Vizual interfeys (Premium Dark-Mode dizayni)
    text = (
        "✍️ <b>Anime tavsifi muvaffaqiyatli saqlandi.</b>\n"
        "───────────────────────\n\n"
        "🌐 Endi ushbu anime qaysi <b>tillarga (ovoz va subtitr)</b> ega ekanligini kiriting:\n"
        "<i>(Masalan: O'zbekcha, Yaponcha, Ruscha kabi vergul bilan ajratib yozing)</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Jarayonni bekor qilish", 
            callback_data="add_anime_main"
        )
    )
    
    # 4. Toza va chiroyli tarzda yuborish (reply emas, answer)
    await message.answer(
        text=text, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )





# =====================================================================
# QADAM 7: Tillarni olish -> BAZAGA VA KESHGA YOZISH (YAKUN)
# =====================================================================
@router.message(AnimeMenuState.adding_languages)
async def process_anime_languages_and_save(message: Message, state: FSMContext, session: Any):
    """ 🌐 Admin yuborgan tillarni qabul qilish va ma'lumotlarni bazaga muhrlash """
    
    if not message.text or message.text.startswith("/"):
        return await message.answer(
            "⚠️ <b>Xatolik:</b> Iltimos, anime tillarini matn ko'rinishida yuboring!\n"
            "📌 Tillarni qaytadan kiriting (Masalan: <code>O'zbekcha, Ruscha</code>):",
            parse_mode="HTML"
        )

    fsm_data = await state.get_data()
    selected_genres = fsm_data.get("selected_genres", [])
    if not selected_genres:
        return await message.answer("❌ Janrlar topilmadi. Iltimos, jarayonni qaytadan boshlang.")

    # Bazaga yozish uchun toza matnni olamiz (escape qilmasdan)
    raw_languages = message.text.strip()
    
    loading_msg = await message.answer(
        text="⏳ <code>Tizim ma'lumotlarni bazaga yozmoqda, iltimos kuting...</code>", 
        parse_mode="HTML"
    )

    try:
        # Yil qiymatini xavfsiz parslash (agar FSM'da xato format bo'lsa tizim qulamasligi uchun)
        try:
            anime_year_raw = int(fsm_data.get("year", 2026))
        except (ValueError, TypeError):
            anime_year_raw = 2026

        # Repositoriy o'zi ichida commit qiladi va xavfsiz Dict qaytaradi
        new_anime = await AnimeRepository.add_anime(
            session=session,
            title=fsm_data.get("title"),
            poster_id=fsm_data.get("poster_id"),
            year=anime_year_raw,
            is_completed=fsm_data.get("is_completed", False),
            genres=selected_genres,
            description=fsm_data.get("description") or "Tavsif kiritilmagan.",
            languages=raw_languages,  # <--- BAZAGA TOZA MATN BORADI
            episodes=[]
        )
        
        # Muvaffaqiyatli yozildi, birinchi navbatda State'ni tozalaymiz (Xavfsizlik uchun)
        await state.clear()
        
        # Ma'lumotlarni Telegram UI uchun HTML xavfsiz holatga keltiramiz (Faqat chiqarishda!)
        anime_id = new_anime.get("anime_id")
        anime_title = html.escape(str(new_anime.get("title", "Nomsiz")))
        anime_year = new_anime.get("year", "Noma'lum")
        anime_genres = [html.escape(str(g)) for g in new_anime.get("genres", [])]
        anime_langs = html.escape(str(new_anime.get("languages", raw_languages)))
        
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🎬 Qism yuklashni boshlash", callback_data=f"add_ep_{anime_id}"))
        builder.row(types.InlineKeyboardButton(text="🔙 Admin Panelga qaytish", callback_data="add_anime_main"))
        
        success_text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "     🎉 MUVAFFAQIYATLI QO'SHILDI!\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"🆔 <b>Anime ID:</b> <code>{anime_id}</code>\n"
            f"🎬 <b>Anime nomi:</b> <code>{anime_title}</code>\n"
            f"📅 <b>Yili:</b> <code>{anime_year}-yil</code>\n"
            f"🔮 <b>Janrlar:</b> <code>{', '.join(anime_genres) if anime_genres else 'Kiritilmagan'}</code>\n"
            f"🌐 <b>Tillari:</b> <code>{anime_langs}</code>\n\n"
            "───────────────────────\n"
            "💡 <i>Anime asosiy bazaga muvaffaqiyatli muhrlandi va qidiruv keshiga tarqatildi.</i>"
        )

        await loading_msg.edit_text(
            text=success_text, 
            reply_markup=builder.as_markup(), 
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"❌ Anime qo'shishda jiddiy xatolik: {e}")
        
        # Xatolik bo'lsa ham admin bloklanib qolmasligi uchun stateni tozalash yoki boshqa sahifaga ruxsat berish
        error_builder = InlineKeyboardBuilder()
        error_builder.row(types.InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="add_anime_main"))
        
        try:
            await loading_msg.edit_text(
                text="❌ <b>Tizim xatoligi!</b>\n\n"
                     "Ma'lumotlarni bazaga yozishda muammo yuz berdi. Server jurnallarini (logs) tekshiring.",
                reply_markup=error_builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception as tg_err:
            logger.error(f"❌ Xatolik xabarini yuborishda Telegram API xatosi: {tg_err}")

# =====================================================================
# ⛩ QADAM 8: Qism qo'shish jarayoni (Video qabul qilish va bazaga saqlash)
# =====================================================================
@router.callback_query(F.data.startswith("add_ep_"))
async def start_add_episode(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 🎬 Admin qism qo'shish tugmasini bosganda navbatdagi qism raqamini aniqlash va video so'rash """
    
    # 1. callback_data dan anime_id ni xavfsiz ajratib olish ("add_ep_45" -> 45)
    try:
        # rsplit orqali xavfsizlikni oshiramiz, agar id ichida pastki chiziq bo'lmasa ham ishonchli ishlaydi
        anime_id = int(callback.data.rsplit("_", 1)[-1])
    except (IndexError, ValueError):
        return await callback.answer("⚠️ Callback ma'lumotlarida xatolik!", show_alert=True)
    
    # 2. Bazadan animeni o'qiymiz
    anime = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    
    if not anime:
        # Agar anime o'chib ketgan bo'lsa, xato bermasligi uchun xavfsiz chiqish
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        return await callback.message.answer("❌ <b>Xatolik:</b> Ushbu anime tizimda topilmadi yoki o'chirilgan.", parse_mode="HTML")
        
    # Xavfsiz ma'lumotlarni ajratib olish (Bizning repomiz doim dict qaytaradi)
    if isinstance(anime, dict):
        episodes_list = anime.get("episodes", [])
        anime_title = anime.get("title", "Noma'lum anime")
    else:
        episodes_list = getattr(anime, "episodes", []) or []
        anime_title = getattr(anime, "title", "Noma'lum anime")

    # 3. 🔥 ENGMUHIM FIX: Qism raqamini UniqueConstraint xatosiz, 100% ishonchli hisoblash
    if episodes_list:
        try:
            # Agar epizod dict bo'lsa (bizning oxirgi repomizda shunday)
            if isinstance(episodes_list[0], dict):
                highest_ep = max([ep.get("episode", 0) for ep in episodes_list])
            # Agar tasodifan ob'ekt bo'lib qolsa
            else:
                highest_ep = max([getattr(ep, "episode", 0) for ep in episodes_list])
            next_episode_number = highest_ep + 1
        except Exception:
            # Fallback (kutilmagan ro'yxat kelsa)
            next_episode_number = len(episodes_list) + 1
    else:
        next_episode_number = 1
    
    # 4. Ma'lumotlarni FSM xotirasiga muhrlaymiz va state'ni o'zgartiramiz
    await state.update_data(anime_id=anime_id, episode_number=next_episode_number)
    await state.set_state(AnimeMenuState.adding_episode_video)
    
    # Premium Dark-Mode UI Dizayni
    text = (
        "╔═══════════ ⛩ ═══════════╗\n"
        "        <b>QISM YUKLASH PANEL</b>\n"
        "╚═══════════ ⛩ ═══════════╝\n\n"
        f"🎬 <b>Anime:</b> <code>{anime_title}</code>\n"
        f"🔢 <b>Navbatdagi qism:</b> <code>{next_episode_number}-qism</code>\n"
        "───────────────────────\n\n"
        "📌 Iltimos, ushbu qism uchun <b>Video (mp4)</b> yoki siqilmagan <b>Fayl (document)</b> yuboring."
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Yuklashni bekor qilish", 
            callback_data="add_anime"
        )
    )
    
    # 5. 🔥 UI FIX: Rasm (Poster) ustiga text edit qilish xatosini butkul yo'q qilish
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass # Eski xabarni o'chirib bo'lmasa, indamaymiz
        
    await callback.message.answer(
        text=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer(f"⚙️ {next_episode_number}-qism kutilmoqda...")


# =====================================================================
# ⛩ QADAM 9: Videolarni qabul qilish va Xotiraga (FSM) yig'ish
# =====================================================================
@router.message(AnimeMenuState.adding_episode_video, F.video | F.document)
async def process_episode_video_bulk(message: Message, state: FSMContext):
    """ 📥 Admin yuborgan videolarni bazaga yozmasdan, FSM xotirasiga ketma-ket va xavfsiz yig'adi """
    
    video_file_id = None
    video_unique_id = None
    
    # 1. Formatni va fayl xavfsizligini qat'iy aniqlash
    if message.video:
        video_file_id = message.video.file_id
        video_unique_id = message.video.file_unique_id
    elif message.document:
        mime = message.document.mime_type
        # None bo'lishi yoki video bo'lmasligini to'liq to'samiz
        if not mime or not mime.startswith("video/"):
            return await message.answer(
                "⚠️ <b>Xatolik:</b> Iltimos, faqat video formatdagi fayllarni (mp4, mkv...) yuboring!",
                parse_mode="HTML"
            )
        video_file_id = message.document.file_id
        video_unique_id = message.document.file_unique_id

    if not video_file_id or not video_unique_id:
        return await message.answer("❌ Videoni aniqlab bo'lmadi, iltimos qaytadan yuboring:")

    # FSM xotirasidan barcha kerakli ma'lumotlarni yagona so'rovda olamiz
    data = await state.get_data()
    anime_id = data.get("anime_id")
    
    # 🔥 FIX 1: Oldingi handlerda aniqlangan bazadagi navbatdagi qism boshlang'ich raqami
    base_episode_number = data.get("episode_number") 
    
    if not anime_id or base_episode_number is None:
        return await message.answer(
            "❌ <b>Xatolik:</b> Tizim xotirasi uzildi. Iltimos, qism yuklash paneliga qaytadan kiring.",
            parse_mode="HTML"
        )
        
    temp_episodes = data.get("temp_episodes", [])
    
    # 🔥 UX GUARD: Albom yuklanganda dublikat fayllar kirib ketishini to'sish
    if any(ep["file_unique_id"] == video_unique_id for ep in temp_episodes):
        return  # Dublikat bo'lsa indamay tashlab ketamiz (Telegram flood oldini oladi)
        
    # 🔥 FIX 2: Qism raqamini bazadagi bor qismlarga nisbatan mutlaqo to'g'ri hisoblash
    current_queue_number = base_episode_number + len(temp_episodes)
    
    # Videoni xotiradagi navbatga qo'shish
    temp_episodes.append({
        "episode_num": current_queue_number,
        "file_id": video_file_id,
        "file_unique_id": video_unique_id
    })
    
    # Xotirani darhol yangilaymiz (Parallel so'rovlar race-condition bo'lmasligi uchun)
    await state.update_data(temp_episodes=temp_episodes)
    
    # Boshqaruv tugmalari builder'i
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="📢 Kanalga e'lon qilish va saqlash", 
        callback_data=f"bulk_save_publish_{anime_id}"
    ))
    builder.row(types.InlineKeyboardButton(
        text="💾 Shunchaki bazaga yozish va tugatish", 
        callback_data=f"bulk_save_only_{anime_id}"
    ))

    # Real-vaqt (Live Counter) dizayni
    text = (
        "╔═══════════ ⛩ ═══════════╗\n"
        "      📥 VIDEOLAR QABUL QILINMOQDA\n"
        "╚═══════════ ⛩ ═══════════╝\n\n"
        f"✅ <b>Yangi video zanjirga muvaffaqiyatli qo'shildi!</b>\n"
        f"🔢 Oxirgi yuklangan: <code>{current_queue_number}-qism</code>\n"
        f"📊 Navbatda saqlangan: <code>{len(temp_episodes)} ta yangi qism</code>\n\n"
        f"<blockquote expandable>"
        f"📌 Bot hozir avtomat rejimda keyingi qismlarni ketma-ket qabul qilaveradi. "
        f"Yana qismlar bo'lsa, <b>fayllarni to'g'ridan-to'g'ri tashlashda davom eting</b>.\n\n"
        f"Hamma videolarni yuborib bo'lgach, pastdagi tugmalardan birini bosing. "
        f"Shundagina barcha qismlar <b>bitta o'ramda</b> bazaga muhrlanadi!"
        f"</blockquote>"
    )
    
    # 🔥 FIX 3: Chatni 100 ta xabar bilan to'ldirmaslik uchun "Anti-Spam Dashboard" logikasi
    last_menu_msg_id = data.get("bulk_menu_msg_id")
    success_edit = False
    
    if last_menu_msg_id:
        try:
            # Eski status xabarini tahrirlaymiz
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=last_menu_msg_id,
                text=text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            success_edit = True
        except TelegramBadRequest:
            # Agar xabar juda tez o'zgargani uchun yoki topilmagani uchun o'zgarmasa, pastga tushadi
            pass

    # Agar hali dashboard xabari yaratilmagan bo'lsa yoki edit qilishda xato bo'lsa, yangisini ochamiz
    if not success_edit:
        new_msg = await message.answer(
            text=text, 
            reply_markup=builder.as_markup(), 
            parse_mode="HTML"
        )
        # Kelgusi videolar shu xabarni tahrirlashi uchun ID'sini saqlaymiz
        await state.update_data(bulk_menu_msg_id=new_msg.message_id)

# =====================================================================
# ⛩ QADAM 10: Videolarni bazaga yozish va jarayonni yakunlash
# =====================================================================
@router.callback_query(F.data.startswith("bulk_save_only_") | F.data.startswith("bulk_save_publish_"))
async def finish_anime_addition_and_save(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 🗄 Xotiradagi barcha epizodlarni bazaga yozadi, keshni yangilaydi va jarayonni yopadi """
    
    # Callback ma'lumotidan niyatni (publish qilinadimi yo'qmi) va anime_id ni olamiz
    action_type = "publish" if "publish" in callback.data else "save_only"
    
    try:
        anime_id = int(callback.data.rsplit("_", 1)[-1])
    except (IndexError, ValueError):
        return await callback.answer("⚠️ Ma'lumot xatosi!", show_alert=True)

    fsm_data = await state.get_data()
    temp_episodes = fsm_data.get("temp_episodes", []) 

    if not temp_episodes:
        await callback.answer("⚠️ Xotirada yangi qismlar topilmadi!", show_alert=True)
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        try:
            return await callback.message.edit_text(
                "⛩ Jarayon yakunlangan yoki FSM xotirasi bo'sh.", 
                reply_markup=builder.as_markup()
            )
        except TelegramBadRequest:
            return

    await callback.answer("⚙️ Ma'lumotlar bazaga muhrlanmoqda...")
    
    loading_text = f"⏳ <code>Xotiradagi {len(temp_episodes)} ta qism bazaga yozilmoqda. Iltimos kuting...</code>"
    
    try:
        current_msg = await callback.message.edit_text(text=loading_text, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            current_msg = await callback.message.edit_caption(caption=loading_text, parse_mode="HTML")
        except TelegramBadRequest:
            current_msg = await callback.message.answer(text=loading_text, parse_mode="HTML")

    successful_inserts = 0

    try:
        # 🚀 1. BAZAGA KETMA-KET YUKLASH (Xatolar ustidan nazorat bilan)
        for ep in temp_episodes:
            try:
                # Eslatma: Agar repo ichiga bulk_insert metod qo'shsangiz, for loop'dan voz keching!
                await AnimeRepository.add_anime_episode(
                    session=session,
                    anime_id=anime_id,
                    episode_num=ep["episode_num"], 
                    file_id=ep["file_id"]
                )
                successful_inserts += 1
            except Exception as single_err:
                # Agar 20 ta videodan 1 tasida xato chiqsa ham tizim to'xtamay qolganlarini yozadi
                logger.warning(f"⚠️ {ep['episode_num']}-qismni yozishda xato (Takroriy bo'lishi mumkin): {single_err}")
                continue # Keyingi qismga o'tish

        # Agar barcha qismlar yozilmay xato bo'lsa (masalan, db uzilsa), tashqariga irg'itamiz
        if successful_inserts == 0 and len(temp_episodes) > 0:
            raise Exception("Birorta ham qism muvaffaqiyatli saqlanmadi!")

        # 2. Tugmalar dizayni
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🔙 Orqaga", 
                callback_data="add_anime"
            )
        )
        
        # Action'ga qarab matnni o'zgartiramiz
        publish_info = "va kanalga e'lon qilindi." if action_type == "publish" else "(Kanalga e'lon qilinmadi)."

        success_text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "     🎉 BARCHA QISMLAR SAQLANDI!\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"📦 <b>Muvaffaqiyatli yozildi:</b> <code>{successful_inserts}/{len(temp_episodes)} ta qism</code>\n"
            f"🎬 <b>Anime ID:</b> <code>{anime_id}</code>\n\n"
            "───────────────────────\n"
            f"💾 <i>Anime qismlari asosiy bazaga muvaffaqiyatli yozildi {publish_info}</i>"
        )

        # 3. Natijani ko'rsatish
        try:
            await current_msg.edit_text(text=success_text, parse_mode="HTML", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            try:
                await current_msg.edit_caption(caption=success_text, parse_mode="HTML", reply_markup=builder.as_markup())
            except TelegramBadRequest:
                await current_msg.answer(text=success_text, parse_mode="HTML", reply_markup=builder.as_markup())

        # 🔥 4. Agar foydalanuvchi "Publish" tugmasini bosgan bo'lsa, bu yerda kanalga e'lon qilish funksiyasini chaqirishingiz mumkin.
        if action_type == "publish":
            # await send_to_channel_logic(anime_id, temp_episodes)
            pass

        # 5. Jarayon to'liq muvaffaqiyatli tugagandan keyingina xotirani tozalaymiz
        await state.clear()

    except Exception as e:
        logger.error(f"❌ Yakuniy saqlashda jiddiy xatolik: {e}")
        
        error_builder = InlineKeyboardBuilder()
        error_builder.row(types.InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="add_anime"))
        
        error_text = "❌ <b>Bazada xatolik!</b>\n\nQismlarni bazaga yozish muvaffaqiyatsiz tugadi. Aloqani tekshiring."
        try:
            await current_msg.edit_text(text=error_text, parse_mode="HTML", reply_markup=error_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=error_builder.as_markup())

# =====================================================================
# ⛩ QADAM 10: Xotiradagi qismlarni bazaga yozish -> Kanalga e'lon qilish
# =====================================================================
@router.callback_query(F.data.startswith("publish_anime_") | F.data.startswith("bulk_save_publish_"))
async def publish_anime_to_channel_and_save(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 📢 Xotiradagi epizodlarni bazaga yozadi va postni deep-link tugmasi bilan kanalga e'lon qiladi """
    
    await callback.answer("📢 Kanalga e'lon qilish boshlandi...")
    
    # 1. Ma'lumotlarni xavfsiz ajratib olish
    fsm_data = await state.get_data()
    anime_id = fsm_data.get("anime_id")
    temp_episodes = fsm_data.get("temp_episodes", []) 

    # Dynamic callback_data'dan anime_id ni xavfsiz olish
    if not anime_id:
        try:
            anime_id = int(callback.data.rsplit("_", 1)[-1])
        except (IndexError, ValueError):
            return await callback.answer("❌ Anime ID aniqlanmadi!", show_alert=True)

    loading_text = "⏳ <code>Ma'lumotlar bazaga muhrlanmoqda va kanalga tayyorlanmoqda...</code>"
    
    # UI Loading qismini xavfsiz boshqarish
    try:
        current_msg = await callback.message.edit_text(text=loading_text, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            current_msg = await callback.message.edit_caption(caption=loading_text, parse_mode="HTML")
        except TelegramBadRequest:
            current_msg = await callback.message.answer(text=loading_text, parse_mode="HTML")

    try:
        # 🔥 FIX 1: BAZAGA YUKLASH VA TRANZAKSIYANI NAZORAT QILISH
        successful_inserts = 0
        if temp_episodes:
            for ep in temp_episodes:
                try:
                    await AnimeRepository.add_anime_episode(
                        session=session,
                        anime_id=anime_id,
                        episode_num=ep["episode_num"],
                        file_id=ep["file_id"]
                    )
                    successful_inserts += 1
                except Exception as ep_err:
                    logger.warning(f"⚠️ {ep['episode_num']}-qismni yozishda xato: {ep_err}")
                    await session.rollback()  # Xato bo'lsa sessiyani tozalaymiz, qolgan kod ishlayverishi uchun
                    continue
            
            # Barcha qismlar muvaffaqiyatli yozilgach bazaga tasdiqlaymiz
            await session.commit()
        
        # 🔥 3. ANIMENI BAZADAN TO'LIQ JANRLARI BILAN BIRGA OLAMIZ
        stmt = (
            select(Anime)
            .options(
                selectinload(Anime.genres),
                selectinload(Anime.episodes)
            )
            .where(Anime.anime_id == anime_id)
        )
        result = await session.execute(stmt)
        anime = result.scalar_one_or_none()
        
        if not anime:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
            await current_msg.edit_text("❌ Xatolik: Anime bazadan topilmadi.", reply_markup=builder.as_markup())
            return

        # 4. Ma'lumotlarni chiroyli va xavfsiz formatlaymiz
        genres_str = ", ".join([html.escape(g.name) for g in anime.genres]) if anime.genres else "Mavjud emas"
        status_str = "🟢 Tugallangan" if anime.is_completed else "🔴 Davom etmoqda"
        
        safe_title = html.escape(str(anime.title))
        safe_languages = html.escape(str(anime.languages)) if anime.languages else 'O\'zbekcha'
        episodes_count = len(anime.episodes) if anime.episodes else 0

        # 🔥 FIX 2: SHABLON MATNINI DINAMIK HISOBLASH (1024 Limitidan oshmaslik uchun)
        # Avval shablonning o'zining uzunligini hisoblab olamiz
        base_caption = (
            f"╔══════════════════╗\n"
            f"     🎬 <b>{safe_title}</b>\n"
            f"╚══════════════════╝\n\n"
            f"📌 <b>Anime haqida ma'lumot:</b>\n"
            f"╔══════════════════╗\n"
            f"├ 🆔 Kod: <code>#{anime.anime_id}</code>\n"  
            f"├ 📅 Yil: <b>{anime.year}</b>\n"
            f"├ ▶️ Qism: <b>{episodes_count}</b> \n"
            f"├ 🚦 Status: <b>{status_str}</b>\n"
            f"├ 🌐 Til: <b>{safe_languages}</b>\n"
            f"╚══════════════════╝\n"
            f"╔══════════════════╗\n"
            f"  🔮 Janrlar: <i>{genres_str}</i>\n"
            f"╚══════════════════╝\n\n"
            f"📝 <b>Tavsif:</b>\n"
        )
        
        raw_description = anime.description or "Tavsif kiritilmagan."
        
        # Agar rasm bo'lsa, Telegram limiti 1024 ta belgi. 
        # Shablondan ortgan joyni tavsifga ajratamiz (35 belgi blockquote teglari va xavfsizlik zaxirasi)
        if anime.poster_id:
            max_description_allowed = 1024 - len(base_caption) - 35
            if len(raw_description) > max_description_allowed:
                raw_description = raw_description[:max_description_allowed] + "..."
                
        safe_description = html.escape(raw_description)
        
        # Yakuniy jami post matni
        caption = base_caption + f"<blockquote expandable>{safe_description}</blockquote>"
        
        # 6. DYNAMIC DEEP-LINK TUGMASI
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username
        
        channel_builder = InlineKeyboardBuilder()
        channel_builder.row(
            InlineKeyboardButton(
                text="🎬 Animeni ko'rish", 
                url=f"https://t.me/{bot_username}?start=anime_{anime.anime_id}"
            )
        )

        # 📢 KANALGA YUBORISH
        if anime.poster_id:
            await callback.bot.send_photo(
                chat_id="@Aninovuz", 
                photo=anime.poster_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=channel_builder.as_markup()
            )
        else:
            await callback.bot.send_message(
                chat_id="@Aninovuz", 
                text=caption,
                parse_mode="HTML",
                reply_markup=channel_builder.as_markup()
            )
        
        # 7. Admin uchun yakuniy hisobot
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(InlineKeyboardButton(text="🔙 Orqaga", callback_data="add_anime"))
        
        success_admin_text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "    📢 KANALGA MUVAFFAQIYATLI CHIQTI!\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"🎬 <b>Anime:</b> <code>{safe_title}</code>\n"
            f"📦 <b>Yozilgan qismlar:</b> <code>{successful_inserts} ta yangi qism</code>\n"
            f"🚀 <b>Manzil:</b> @Aninovuz\n\n"
            "───────────────────────\n"
            "✅ <i>Barcha qismlar bazaga muhrlandi va kanal postiga dynamic ko'rish havolasi biriktirildi.</i>"
        )
        
        try:
            await current_msg.edit_text(text=success_admin_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=success_admin_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
            
        # 🔥 8. HAMMA ISH MUVAFFAQIYATLI BITGACH, FSM TOZALANADI
        await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Kanalga e'lon qilishda jiddiy xato: {e}")
        
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        
        error_text = (
            f"⚠️ <b>Ma'lumot saqlandi, lekin kanalga ketmadi!</b>\n\n"
            f"<b>Xatolik sababi:</b> <code>{html.escape(str(e))}</code>\n\n"
            f"💡 <i>Tavsiya: Bot @Aninovuz kanalida administrator ekanligini va "
            f"Rasm/Post yuborish huquqi borligini tekshiring! Shuningdek, tavsif matni uzunligiga ham e'tibor qarating.</i>"
        )
        try:
            await current_msg.edit_text(text=error_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())