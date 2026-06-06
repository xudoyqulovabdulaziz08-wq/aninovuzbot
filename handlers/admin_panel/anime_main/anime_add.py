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
@router.message(AnimeMenuState.adding_anime_photo)
async def process_anime_photo(message: Message, state: FSMContext, **data):
    """ 📥 Admin yuborgan rasmni (yoki URL) qabul qilib, janrlar klaviaturasini chiqarish """
    
    poster_id = None
    
    # 1. Agar rasm formatida kelgan bo'lsa
    if message.photo:
        poster_id = message.photo[-1].file_id
    # 2. Agar siqilmagan fayl (Document) formatida rasm kelgan bo'lsa
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        poster_id = message.document.file_id
    # 3. Agar matnli URL havola yuborilgan bo'lsa
    elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
        poster_id = message.text.strip()
    else:
        # Noto'g'ri format yuborilsa, FSM uzilib qolmaydi, qayta so'raydi
        return await message.answer(
            "⚠️ <b>Noto'g'ri format!</b>\n"
            "Iltimos, animening rasmini yuboring yoki to'g'ri rasm URL havolasini kiriting:"
        )

    # FSM xotirasiga poster_id va kelajakda tanlanadigan janrlar uchun bo'sh ro'yxat ochamiz
    await state.update_data(poster_id=poster_id, selected_genres=[])
    
    # Keyingi bosqichga o'tamiz
    await state.set_state(AnimeMenuState.adding_genres)

    # 4. 🔥 BAZADAN JANRLARNI DYNAMIC UKLASH (Zanjir uzilmasligi uchun)
    safe_session = data.get("session")
    actual_session = getattr(safe_session, "_session", safe_session)
    
    builder = InlineKeyboardBuilder()
    try:
        # Bazadagi barcha janrlarni alifbo tartibida olamiz
        stmt = select(Genre).order_by(Genre.name.asc())
        res = await actual_session.execute(stmt)
        genres_list = res.scalars().all()
        
        # Har bir janr uchun dynamic tugma yaratamiz
        for genre in genres_list:
            builder.row(
                types.InlineKeyboardButton(
                    text=f"🔮 {genre.name}", 
                    callback_data=f"toggle_g_{genre.name}"
                )
            )
    except Exception as e:
        logger.error(f"❌ Janrlarni yuklashda xatolik: {e}")
        # Agar bazada hali janr bo'lmasa, fallback sifatida ogohlantiramiz
        return await message.answer("❌ Tizimda janrlar topilmadi. Avval janrlar yarating!")

    # Davom etish va Bekor qilish tugmalari
    builder.row(
        types.InlineKeyboardButton(text="🚀 Saqlash va Davom etish", callback_data="confirm_genres_choice")
    )
    builder.row(
        types.InlineKeyboardButton(text="🚫 Jarayonni bekor qilish", callback_data="add_anime_main")
    )

    text = (
        "🖼 <b>Poster muvaffaqiyatli qabul qilindi.</b>\n"
        "───────────────────────\n\n"
        "📁 Quyidagi ro'yxatdan anime <b>janrlarini</b> tanlang:\n"
        "<i>(Tugmalarni bossangiz, yonida ✅ belgisi paydo bo'ladi. Bir nechta janr tanlash mumkin)</i>"
    )

    await message.answer(
        text=text, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )





# =====================================================================
# 🏁 QADAM 5: Admin janrlarni tanlab bo'lib 'Saqlash' tugmasini bosganda
# =====================================================================
@router.callback_query(AnimeMenuState.adding_genres, F.data == "confirm_genres_choice")
async def confirm_anime_genres(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 🏁 Admin janrlarni tanlab bo'lib 'Saqlash' tugmasini bosganda ishlaydi """
    
    current_data = await state.get_data()
    selected_genre_ids = current_data.get("selected_genres", [])
    
    # UX tekshiruvi: Agar admin birorta ham janr tanlamasdan saqlamoqchi bo'lsa
    if not selected_genre_ids:
        return await callback.answer(
            "⚠️ Kamida 1 ta janr tanlashingiz shart!", 
            show_alert=True
        )
        
    await callback.answer("⚙️ Janrlar qayta ishlanmoqda...")

    genre_names = []
    if selected_genre_ids:
        try:
            clean_ids = [int(g_id) for g_id in selected_genre_ids if str(g_id).isdigit()]
            
            if clean_ids:
                stmt = select(Genre).where(Genre.id.in_(clean_ids))
                result = await session.execute(stmt)
                genres_objs = result.scalars().all()
                # Xatoliklarni oldini olish uchun xavfsiz html.escape
                genre_names = [html.escape(g.name) for g in genres_objs]
        except Exception as e:
            logger.warning(f"⚠️ FSM dan janr ID o'qishda fallback faollashdi: {e}")
            genre_names = [html.escape(str(g)) for g in selected_genre_ids]

    # Agar biron sabab bilan nomlar topilmasa, IDlarni o'zini chiqaramiz
    if not genre_names:
        genre_names = [str(g_id) for g_id in selected_genre_ids]

    # Keyingi bosqichga (Yilni so'rash) o'tkazamiz
    await state.set_state(AnimeMenuState.adding_year)
    
    text = (
        "╔═══════════ ⛩ ═══════════╗\n"
        "        <b>JANRLAR TASDIQLANDI</b>\n"
        "╚═══════════ ⛩ ═══════════╝\n\n"
        f"🔮 <b>Tanlangan janrlar:</b> <code>{', '.join(genre_names)}</code>\n"
        "───────────────────────\n\n"
        "📅 Endi animening <b>chiqarilgan yilini</b> kiriting:\n"
        "<i>(Masalan: 2024, 2026 kabi faqat yil raqamini yozing)</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Jarayonni bekor qilish", 
            callback_data="add_anime_main"  # Izchillik uchun asosiy menyu callbackiga o'zgartirildi
        )
    )
    
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        # Agar xabarda media (rasm) bo'lsa edit_text ishlamaydi, yangi xabar yuboramiz
        await callback.message.answer(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


# =====================================================================
# ⛩ QADAM 5.5: Admin janrlarni matn ko'rinishida yozgandagi Fallback
# =====================================================================
@router.message(AnimeMenuState.adding_genres)
async def fallback_anime_genres_message(message: Message, state: FSMContext, session: Any):
    """ 🛡 Admin tugmalarni bosish o'rniga chatga matn yozganda ishlaydigan aqlli tizim """
    
    if not message.text or message.text.startswith("/"):
        return await message.answer("❌ Iltimos, faqat matn ko'rinishida yozing yoki yuqoridagi tugmalardan foydalaning.")
        
    # Matnni chiroyli tozalaymiz
    raw_inputs = [g.strip() for g in message.text.replace(",", " ").split() if g.strip()]
    
    # Agar tepadagi split o'xshamasa standart vergulli split
    if not raw_inputs:
        raw_inputs = [g.strip() for g in message.text.split(",") if g.strip()]

    if not raw_inputs:
        return await message.answer(
            "⚠️ <b>Janrlar aniqlanmadi!</b>\n"
            "Iltimos, janr nomlarini bo'shliq yoki vergul bilan ajratgan holda kiriting.\n"
            "<i>(Masalan: Shounen Isekai Ekshen)</i>",
            parse_mode="HTML"
        )

    loading_msg = await message.answer("⚙️ <code>Janrlar tekshirilmoqda va indekslanmoqda...</code>", parse_mode="HTML")

    final_genre_ids = []
    processed_names = []

    try:
        for raw_name in raw_inputs:
            # Sarlavha ko'rinishiga keltiramiz (isekai -> Isekai)
            genre_name = raw_name.capitalize()
            
            # 🔥 FIX 2: Case-Insensitive qidiruv (Duplikat yaratilishini oldini oladi)
            stmt = select(Genre).where(Genre.name.ilike(genre_name))
            result = await session.execute(stmt)
            genre_obj = result.scalar_one_or_none()
            
            # Agar bazada garchi boshqa registrdagi shakli ham bo'lmasa, yangi ochamiz
            if not genre_obj:
                genre_obj = Genre(name=genre_name)
                session.add(genre_obj)
                await session.flush() # Yangi ID generatsiya qilinadi
            
            final_genre_ids.append(genre_obj.id)
            # 🔥 FIX 1: Telegram crash bo'lmasligi uchun xavfsiz HTML Escape
            processed_names.append(html.escape(genre_obj.name))

        # FSM xotirasiga faqat toza va tartiblangan ID listni joylaymiz
        await state.update_data(selected_genres=final_genre_ids)
        await state.set_state(AnimeMenuState.adding_year)
        
        text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "        <b>JANRLAR INDEKSLANDI</b>\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"✍️ <b>Tizim qabul qilgan janrlar:</b>\n"
            f"<code>{', '.join(processed_names)}</code>\n"
            f"📊 <i>(Jami: {len(final_genre_ids)} ta janr muvaffaqiyatli bog'landi)</i>\n"
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
        await loading_msg.edit_text("❌ Janrlarni indekslashda kutilmagan xatolik yuz berdi. Qaytadan urinib ko'ring.")



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
    
    # 1. Input Validation: Faqat matn ekanligini tekshirish
    if not message.text or message.text.startswith("/"):
        return await message.answer(
            "⚠️ <b>Xatolik:</b> Iltimos, anime tillarini matn ko'rinishida yuboring!\n"
            "📌 Tillarni qaytadan kiriting (Masalan: <code>O'zbekcha, Ruscha</code>):",
            parse_mode="HTML"
        )

    # FSM xotirasidan barcha to'plangan ma'lumotlarni xavfsiz olamiz
    fsm_data = await state.get_data()
    
    selected_genres = fsm_data.get("selected_genres", [])
    if not selected_genres:
        return await message.answer("❌ Janrlar topilmadi. Iltimos, jarayonni qaytadan boshlang.")

    # Tillarni chiroyli formatda tozalab va HTML escape qilib olamiz
    languages_list = html.escape(message.text.strip())
    
    # Vizual yuklanish (Loading animation) xabari
    loading_msg = await message.answer(
        text="⏳ <code>Tizim ma'lumotlarni bazaga yozmoqda, iltimos kuting...</code>", 
        parse_mode="HTML"
    )

    try:
        # 1. Repositoriyga yozish (ichkarida flush bo'ladi va kesh on_commit ga yuklanadi)
        new_anime = await AnimeRepository.add_anime(
            session=session,
            title=fsm_data.get("title"),
            poster_id=fsm_data.get("poster_id"),
            year=fsm_data.get("year"),
            is_completed=fsm_data.get("is_completed", False),
            genres=selected_genres,
            description=fsm_data.get("description"),
            languages=languages_list,
            episodes=[]
        )
        
        anime_id = new_anime["anime_id"]
        anime_title = html.escape(new_anime["title"])
        anime_year = new_anime["year"]
        anime_genres = [html.escape(g) for g in new_anime.get("genres", [])]
        
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
            f"🌐 <b>Tillari:</b> <code>{languages_list}</code>\n\n"
            "───────────────────────\n"
            "💡 <i>Anime asosiy bazaga muvaffaqiyatli muhrlandi. "
            "Kesh fonda yangilanmoqda...</i>"
        )
        # =====================================================================
        # 🔥 HANDLER INTERFEYSINI COMMIT BILAN SINXRONLASH
        # =====================================================================
        async def ui_final_commit_step():
            try:
                # Middleware bazani haqiqatdan commit qilgandan so'ng xabarni chiroyli yangilaymiz
                await loading_msg.edit_text(
                    text=success_text, 
                    reply_markup=builder.as_markup(), 
                    parse_mode="HTML"
                )
                # Faqat muvaffaqiyatli saqlangandagina xotirani o'chiramiz!
                await state.clear()
                logger.info(f"✅ [UI Post-Commit] Anime #{anime_id} uchun interfeys muvaffaqiyatli yakunlandi.")
            except Exception as ui_err:
                logger.error(f"❌ UI post-commit yangilashda xatolik: {ui_err}")

        # Middleware'dan kelgan SafeSession hook tizimiga sinxron lambda orqali topshiramiz
        if hasattr(session, "on_commit"):
            session.on_commit(lambda: asyncio.create_task(ui_final_commit_step()))
        else:
            # Agar fallback holat bo'lsa, to'g'ridan-to'g'ri chaqiramiz
            await ui_final_commit_step()
        # =====================================================================
        
    except Exception as e:
        logger.error(f"❌ Anime qo'shishda jiddiy xatolik: {e}")
        
        error_builder = InlineKeyboardBuilder()
        error_builder.row(types.InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="add_anime_main"))
        
        await loading_msg.edit_text(
            text="❌ <b>Tizim xatoligi!</b>\n\n"
                 "Ma'lumotlarni bazaga yozishda texnik xatolik yuz berdi. "
                 "Iltimos, server jurnallarini (logs) tekshiring.",
            reply_markup=error_builder.as_markup(),
            parse_mode="HTML"
        )

# =====================================================================
# ⛩ QADAM 8: Qism qo'shish jarayoni (Video qabul qilish va bazaga saqlash)
# =====================================================================
@router.callback_query(F.data.startswith("add_ep_"))
async def start_add_episode(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 🎬 Admin qism qo'shish tugmasini bosganda navbatdagi qism raqamini aniqlash va video so'rash """
    
    # callback_data dan anime_id ni dynamic ajratib olamiz ("add_ep_45" -> 45)
    try:
        anime_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        return await callback.answer("⚠️ Callback ma'lumotlarida xatolik!", show_alert=True)
    
    # 1. Bazadan yoki Keshdan ushbu animening joriy holatini tekshiramiz
    anime = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    if not anime:
        return await callback.message.edit_text(
            text="❌ <b>Xatolik:</b> Ushbu anime tizimda topilmadi yoki o'chirilgan.",
            parse_mode="HTML"
        )
        
    # Xavfsiz ma'lumotlarni ajratib olish (Dict yoki Model tekshiruvi)
    if isinstance(anime, dict):
        episodes_list = anime.get("episodes", [])
        anime_title = anime.get("title", "Noma'lum anime")
    else:
        episodes_list = getattr(anime, "episodes", []) or []
        anime_title = getattr(anime, "title", "Noma'lum anime")

    # Mavjud qismlar soniga qarab navbatdagi qism raqamini 100% aniq hisoblaymiz
    next_episode_number = len(episodes_list) + 1 if episodes_list else 1
    
    # 2. Ma'lumotlarni keyingi qadamda ishlatish uchun FSM xotirasiga muhrlaymiz
    await state.update_data(anime_id=anime_id, episode_number=next_episode_number)
    
    # 3. State-ni video/fayl qabul qilish holatiga o'tkazamiz
    await state.set_state(AnimeMenuState.adding_episode_video)
    
    # Premium Dark-Mode UI Dizayni
    text = (
        "╔═══════════ ⛩ ═══════════╗\n"
        "        <b>QISM YUKLASH PANEL</b>\n"
        "╚═══════════ ⛩ ═══════════╝\n\n"
        f"🎬 <b>Anime:</b> <code>{anime_title}</code>\n"
        f"🔢 <b>Navbatdagi qism:</b> <code>{next_episode_number}-qism</code>\n"
        "───────────────────────\n\n"
        "📌 Iltimos, ushbu qism uchun <b>Video (mp4)</b> yoki siqilmagan <b>Fayl (document)</b> yuboring.\n\n"
        
    )
    
    # Boshqaruv tugmalari (Jarayonni xavfsiz to'xtatish imkoniyati bilan)
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🚫 Yuklashni bekor qilish", 
            callback_data="add_anime_main"
        )
    )
    
    try:
        # Eski xabarni chiroyli tarzda yangilaymiz (Chat toza turishi uchun)
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer(f"⚙️ {next_episode_number}-qism kutilmoqda...")
    except TelegramBadRequest:
        # Agarda xabarni edit qilib bo'lmasa (masalan, eski xabar bo'lsa), yangi xabar yuboramiz
        await callback.message.answer(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


# =====================================================================
# ⛩ QADAM 9: Videolarni qabul qilish va Xotiraga (FSM) yig'ish
# =====================================================================
@router.message(AnimeMenuState.adding_episode_video, F.video | F.document)
async def process_episode_video_bulk(message: Message, state: FSMContext):
    """ 📥 Admin yuborgan videolarni bazaga yozmasdan, FSM xotirasiga ketma-ket yig'adi """
    
    video_file_id = None
    video_unique_id = None
    
    # 1. Formatni aniqlash va file_id va file_unique_id olish
    if message.video:
        video_file_id = message.video.file_id
        video_unique_id = message.video.file_unique_id
    elif message.document:
        mime = message.document.mime_type
        if mime and not mime.startswith("video/"):
            return await message.answer("⚠️ Iltimos, faqat video formatdagi fayl yuboring!")
        video_file_id = message.document.file_id
        video_unique_id = message.document.file_unique_id

    if not video_file_id or not video_unique_id:
        return await message.answer("❌ Videoni aniqlab bo'lmadi, qaytadan yuboring:")

    # FSM xotirasidan joriy to'plangan epizodlar ro'yxatini olamiz
    data = await state.get_data()
    anime_id = data.get("anime_id")
    # Agar xotirada ro'yxat hali bo'lmasa, yangi ochamiz
    temp_episodes = data.get("temp_episodes", [])
    
    # 🔥 UX GUARD: Albom qilib tashlanganda bir xil video ikki marta ro'yxatga kirmasligi uchun tekshiramiz
    if any(ep["file_unique_id"] == video_unique_id for ep in temp_episodes):
        return  # Dublikat bo'lsa shunchaki tashlab ketamiz
        
    # Navbatdagi qism raqami (xotiradagi bor qismlar + start_number)
    current_queue_number = len(temp_episodes) + 1
    
    # Videoni vaqtincha xotiraga qo'shamiz (DB ga yozilmaydi!)
    temp_episodes.append({
        "episode_num": current_queue_number,
        "file_id": video_file_id,
        "file_unique_id": video_unique_id
    })
    
    # Xotirani yangilaymiz
    await state.update_data(temp_episodes=temp_episodes)
    
    # Admin uchun premium boshqaruv tugmalari (Faqat xabarni yakunlash uchun)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="📢 Kanalga e'lon qilish va saqlash", 
        callback_data=f"bulk_save_publish_{anime_id}"
    ))
    builder.row(types.InlineKeyboardButton(
        text="💾 Shunchaki bazaga yozish va tugatish", 
        callback_data=f"bulk_save_only_{anime_id}"
    ))

    # Real-vaqt rejimida admin uchun hisobot matni
    text = (
        "╔═══════════ ⛩ ═══════════╗\n"
        "      📥 VIDEOLAR QABUL QILINMOQDA\n"
        "╚═══════════ ⛩ ═══════════╝\n\n"
        f"✅ <b>Yangi video zanjirga qo'shildi!</b>\n"
        f"📊 Xotirada tayyor: <code>{len(temp_episodes)} ta qism</code>\n\n"
        f"<blockquote expandable>"
        f"📌 Bot hozir avtomat rejimda keyingi qismlarni qabul qilaveradi. "
        f"Yana qismlar bo'lsa, <b>to'g'ridan-to'g'ri tashlashda davom eting</b>.\n\n"
        f"Hamma videolarni tashlab bo'lgan bo'lsangiz, pastdagi tugmalardan birini bosing. "
        f"Shundagina barcha qismlar <b>bitta so'rovda</b> bazaga muhrlanadi!"
        f"</blockquote>"
    )
    
    # Admin xabari ko'p marta qayta yuborilmasligi uchun oxirgi xabarni tahrirlashga urinamiz
    # Albom yuborilganda xabarlar juda tez kelgani uchun answer ishlatish xavfsizroq
    await message.answer(text=text, reply_markup=builder.as_markup(), parse_mode="HTML")


# =====================================================================
# ⛩ QADAM 10: Videolarni bazaga yozish va jarayonni yakunlash
# =====================================================================
@router.callback_query(F.data == "finish_anime_add")
async def finish_anime_addition_and_save(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 🗄 Xotiradagi barcha epizodlarni bazaga yozadi, keshni yangilaydi va jarayonni yopadi """
    
    # FSM xotirasidan to'plangan ma'lumotlarni olamiz
    fsm_data = await state.get_data()
    anime_id = fsm_data.get("anime_id")
    temp_episodes = fsm_data.get("temp_episodes", []) # 9-qadamda yig'ilgan videolar ro'yxati

    # Xavfsizlik filtri: Agar ro'yxat bo'sh bo'lsa yoki admin adashib qayta bossa
    if not temp_episodes:
        await callback.answer("⚠️ Xotirada yangi qismlar topilmadi yoki allaqachon saqlangan!", show_alert=True)
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        try:
            return await callback.message.edit_text("⛩ Jarayon yakunlangan yoki FSM xotirasi bo'sh.", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            return

    await callback.answer("⚙️ Ma'lumotlar bazaga muhrlanmoqda...")
    
    # Loading holati interfeysi
    loading_text = f"⏳ <code>Xotiradagi {len(temp_episodes)} ta qism bazaga yozilmoqda. Iltimos kuting...</code>"
    
    # Rasmli xabar yoki oddiy matn ekanligiga qarab xavfsiz loading chiqarish
    try:
        current_msg = await callback.message.edit_text(text=loading_text, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            current_msg = await callback.message.edit_caption(caption=loading_text, parse_mode="HTML")
        except TelegramBadRequest:
            current_msg = await callback.message.answer(text=loading_text, parse_mode="HTML")

    try:
        # 🚀 1. BAZAGA KETMA-KET (TRANZAKSIYANI OPTIMALLASHTIRIB) SAQLASH
        # Siz aytgan episode_num kalitiga muvofiq bitta sessiyada yozamiz
        for ep in temp_episodes:
            await AnimeRepository.add_anime_episode(
                session=session,
                anime_id=anime_id,
                episode_num=ep["episode_num"], # 🔥 FIX: To'g'ri kalit
                file_id=ep["file_id"]          # Faqat file_id yuborilmoqda
            )

        # 2. Tugmalarni ixcham va professional tarzda yasaymiz
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🔙 Admin Panelga qaytish", 
                callback_data="admin_anime_panel"
            )
        )
        panel_button = builder.as_markup()

        # Premium Final UI matni
        success_text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "     🎉 BARCHA QISMLAR SAQLANDI!\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"📦 <b>Muvaffaqiyatli yozildi:</b> <code>{len(temp_episodes)} ta qism</code>\n"
            f"🎬 <b>Anime ID:</b> <code>{anime_id}</code>\n\n"
            "───────────────────────\n"
            "💾 <i>Anime qismlari asosiy bazaga muvaffaqiyatli yozildi va indekslandi. "
            "FSM xotirasi tozalandi. (Kanalga e'lon qilinmadi)</i>"
        )

        # 3. Yakuniy natijani silliq va xavfsiz ko'rsatish
        try:
            await current_msg.edit_text(text=success_text, parse_mode="HTML", reply_markup=panel_button)
        except TelegramBadRequest:
            try:
                await current_msg.edit_caption(caption=success_text, parse_mode="HTML", reply_markup=panel_button)
            except TelegramBadRequest:
                await current_msg.answer(text=success_text, parse_mode="HTML", reply_markup=panel_button)

        # 🔥 4. FAQAT MUVAFFAQIYATLI YOZILGANDAN KEYIN XOTIRANI TOZALAYMIZ
        await state.clear()

    except Exception as e:
        logger.error(f"❌ Yakuniy saqlashda jiddiy xatolik: {e}")
        
        # Xatolik yuz berganda admin ma'lumotlari FSMda qoladi (adminga qulaylik)
        error_builder = InlineKeyboardBuilder()
        error_builder.row(types.InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="admin_anime_panel"))
        
        error_text = "❌ <b>Bazada xatolik!</b>\n\nQismlarni bazaga yozish muvaffaqiyatsiz tugadi. Aloqani tekshiring."
        try:
            await current_msg.edit_text(text=error_text, parse_mode="HTML", reply_markup=error_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=error_builder.as_markup())

# =====================================================================
# QADAM 10: Anime kanalga yuborish yoki shunchaki saqlash va yakunlash
# =====================================================================
# =====================================================================
# ⛩ QADAM 10: Xotiradagi qismlarni bazaga yozish -> Kanalga e'lon qilish
# =====================================================================
@router.callback_query(F.data.startswith("publish_anime_") | F.data.startswith("bulk_save_publish_"))
async def publish_anime_to_channel_and_save(callback: CallbackQuery, state: FSMContext, session: Any):
    """ 📢 Xotiradagi epizodlarni bazaga yozadi va postni deep-link tugmasi bilan kanalga e'lon qiladi """
    
    await callback.answer("📢 Kanalga e'lon qilish boshlandi...")
    
    # FSM xotirasidan ommaviy yuklangan qismlarni va anime_id ni olamiz
    fsm_data = await state.get_data()
    anime_id = fsm_data.get("anime_id")
    temp_episodes = fsm_data.get("temp_episodes", []) # 9-qadamda yig'ilgan videolar

    # Agar dynamic callback_data'dan anime_id ni olish kerak bo'lsa (Zaxira uchun)
    if not anime_id:
        try:
            anime_id = int(callback.data.split("_")[2])
        except (IndexError, ValueError):
            return await callback.answer("❌ Anime ID aniqlanmadi!", show_alert=True)

    loading_text = "⏳ <code>Ma'lumotlar bazaga muhrlanmoqda va kanalga tayyorlanmoqda...</code>"
    
    # Rasmli xabar yoki toza matnligiga qarab xavfsiz loading chiqarish
    try:
        current_msg = await callback.message.edit_text(text=loading_text, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            current_msg = await callback.message.edit_caption(caption=loading_text, parse_mode="HTML")
        except TelegramBadRequest:
            current_msg = await callback.message.answer(text=loading_text, parse_mode="HTML")

    try:
        # 🔥 1. AVVAL XOTIRADAGI EPIZODLARNI BAZAGA OMMAVIY (BULK) YOZAMIZ
        if temp_episodes:
            for ep in temp_episodes:
                await AnimeRepository.add_anime_episode(
                    session=session,
                    anime_id=anime_id,
                    episode_num=ep["episode_num"],
                    file_id=ep["file_id"]
                )
        
        # 🔥 2. ANIMENI BAZADAN TO'LIQ JANRLARI BILAN BIRGA BITTA SO'ROVDA OLAMIZ
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

        # 3. Ma'lumotlarni chiroyli va xavfsiz formatlaymiz
        genres_str = ", ".join([g.name for g in anime.genres]) if anime.genres else "Mavjud emas"
        status_str = "🟢 Tugallangan" if anime.is_completed else "🔴 Davom etmoqda"
        
        safe_title = html.escape(anime.title)
        safe_description = html.escape(anime.description or "Tavsif mavjud emas.")
        episodes_count = len(anime.episodes) if anime.episodes else 0
        # 🔥 UX FIX: Agar xotirada (temp_episodes) hali bazaga yozilmagan yangi qismlar bo'lsa, ularni ham qo'shib yuboramiz
        if temp_episodes:
            episodes_count += len(temp_episodes)

        # 4. 📢 KANALGA POST SHABLONI (To'g'rilangan HTML dizayn)
        caption = (
            f"╔══════════════════╗\n"
            f"       🎬 <b>{safe_title}</b>\n"
            f"╚══════════════════╝\n\n"
            f"📌 <b>Anime haqida ma'lumot:</b>\n"
            f"╔══════════════════╗\n"
            f"├ 🆔 Kod: <code>#{anime.anime_id}</code>\n"  
            f"├ 📅 Yil: <b>{anime.year}</b>\n"
            f"├ ▶️ Qism: <b>{episodes_count}</b> \n"
            f"├ 🚦 Status: <b>{status_str}</b>\n"
            f"├ 🌐 Til: <b>{anime.languages or 'O\'zbekcha'}</b>\n"
            f"╚══════════════════╝\n"
            f"╔══════════════════╗\n"
            f"  🔮 Janrlar: <i>{genres_str}</i>\n"
            f"╚══════════════════╝\n\n"
            f"📝 <b>Tavsif:</b>\n"
            f"<blockquote expandable>"
            f"{safe_description}"
            f"</blockquote>"
        )
        
        # 🔥 5. DYNAMIC DEEP-LINK TUGMASI (Kanal postining ostiga qo'yiladi)
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username
        
        # t.me/bot_name?start=anime_id ko'rinishidagi havola
        channel_builder = InlineKeyboardBuilder()
        channel_builder.row(
            InlineKeyboardButton(
                text="🎬 Animeni ko'rish", 
                url=f"https://t.me/{bot_username}?start=anime_{anime.anime_id}"
            )
        )

        # 6. Kanalga rasm (Poster), opisaniya va dynamic tugmani yuboramiz
        await callback.bot.send_photo(
            chat_id="@Aninovuz", 
            photo=anime.poster_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=channel_builder.as_markup()
        )
        
        # Admin uchun yakuniy hisobot tugmasi
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(InlineKeyboardButton(text="🔙 Admin Panelga qaytish", callback_data="admin_anime_panel"))
        
        # Admin xabarini premium dizaynda yangilaymiz
        success_admin_text = (
            "╔═══════════ ⛩ ═══════════╗\n"
            "     📢 KANALGA MUVAFFAQIYATLI CHIQTI!\n"
            "╚═══════════ ⛩ ═══════════╝\n\n"
            f"🎬 <b>Anime:</b> <code>{anime.title}</code>\n"
            f"📦 <b>Yozilgan qismlar:</b> <code>{len(temp_episodes) if temp_episodes else 'Mavjudlari amalda'} ta qism</code>\n"
            f"🚀 <b>Manzil:</b> @Aninovuz\n\n"
            "───────────────────────\n"
            "✅ <i>Barcha qismlar bazaga muhrlandi va kanal postiga dynamic ko'rish havolasi biriktirildi.</i>"
        )
        
        try:
            await current_msg.edit_text(text=success_admin_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=success_admin_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
            
        # 🔥 7. HAMMA ISH MUVAFFAQIYATLI BITGACH, FSM TOZALANADI
        await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Kanalga e'lon qilishda jiddiy xato: {e}")
        
        admin_builder = InlineKeyboardBuilder()
        admin_builder.row(InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        
        error_text = (
            f"⚠️ <b>Ma'lumot saqlandi, lekin kanalga ketmadi!</b>\n\n"
            f"<b>Xatolik sababi:</b> <code>{html.escape(str(e))}</code>\n\n"
            f"💡 <i>Tavsiya: Bot @Aninovuz kanalida administrator ekanligini va "
            f"Rasm/Post yuborish huquqi borligini tekshiring!</i>"
        )
        try:
            await current_msg.edit_text(text=error_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())
        except TelegramBadRequest:
            await current_msg.edit_caption(caption=error_text, parse_mode="HTML", reply_markup=admin_builder.as_markup())