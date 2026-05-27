import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from typing import Any, Optional
from aiogram.filters.callback_data import CallbackData


from sqlalchemy import select
from sqlalchemy.orm import selectinload


from database.repository import AnimeRepository
from database.connection import AsyncSession, async_sessionmaker

from config import config
from keyboards.inline import anime_menu_kb
from database.repository import AnimeRepository
from database.connection import AsyncSession
from database.models import Anime, Genre


router = Router()
logger = logging.getLogger(__name__)
CREATOR_ID = getattr(config, 'CREATOR_ID')


class AnimeMenuState(StatesGroup):
    adding_anime_name = State() # 1 yangi anime qo'shish uchun nomini kiritish
    adding_anime_photo = State() # 2 yangi anime qo'shish uchun rasmni kiritish
    adding_genres = State() # 3 yangi anime qo'shish uchun janrlarni kiritish
    adding_year = State() # 5 yangi anime qo'shish uchun chiqarilgan yilni kiritish
    adding_description = State() # 6 yangi anime qo'shish uchun tavsifni kiritish
    adding_laguages = State() # 7 yangi anime qo'shish uchun tillarni kiritish
    adding_episode_video = State()
    deleting_anime = State()
    updating_anime = State()

class AnimeMenuCallbacks:
    ADD_ANIME = "add_anime"
    ADD_GENRES = "add_genres"
    ADD_YEAR = "add_year"
    ADD_DESCRIPTION = "add_description"
    ADD_EPISODE = "add_episode"
    ADD_PHOTO = "add_photo"
    ADD_LANGUAGES = "add_languages"
    DELETE_ANIME = "delete_anime"
    UPDATE_ANIME = "update_anime"

    
class AnimePageCallback(CallbackData, prefix="anime_page"):
    page: int

class AnimeDetailCallback(CallbackData, prefix="anime_detail"):
    anime_id: int
    page: int

#==============================anime_menu================================#
#========================================================================#
@router.callback_query(F.data == "admin_anime_panel")
async def admin_anime_panel(callback: types.CallbackQuery, state: FSMContext): # event o'rniga callback
    await state.clear()

    text = (
        f"🎛️ <b>ANIME BOSHQARUV MENUSI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Xush kelibsiz, <b>{callback.from_user.full_name}</b>!\n\n"
        f"Boshqaruv paneli yuklandi.\n"
        f"Quyidagi bo'limlardan birini tanlang:\n"
    )
    
    kb = anime_menu_kb()

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Anime panel xatosi: {e}")
    finally:
        await callback.answer("🎛️ Anime boshqaruv menyusi")








# =====================================================================
# QADAM 1: Anime qo'shish boshlanishi
# =====================================================================
@router.callback_query(F.data == "AnimeMenuCallbacks.ADD_ANIME")
async def admin_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer("📌 Yangi anime qo'shish jarayoni boshlandi!")
    
    await state.set_state(AnimeMenuState.adding_anime_name)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_anime_panel"))
    
    await callback.message.answer(
        "📌 Yangi animening **nomini** kiriting:",
        reply_markup=builder.as_markup()
    )
    
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Inline tugmalarni o'chirishda xato: {e}")




# =====================================================================
# QADAM 2: Nomni qabul qilish -> Rasm so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_anime_name)
async def process_anime_name(message: Message, state: FSMContext):
    if not message.text:
        await message.reply("❌ Iltimos, faqat matnli xabar yuboring. Yangi anime nomini kiriting:")
        return
    
    # 💡 Repozitoriyga to'g'ri borishi uchun 'title' kaliti bilan saqlaymiz
    await state.update_data(title=message.text.strip())
    
    await state.set_state(AnimeMenuState.adding_anime_photo)

    builder = InlineKeyboardBuilder()
    # ✨ To'g'rilandi: Qo'shtirnoqsiz va admin panelga xavfsiz qaytadigan qilindi
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_anime_panel"))
    
    await message.reply(
        "📌 Endi anime posterining **rasmini** yuboring:", 
        reply_markup=builder.as_markup()
    )




# =====================================================================
# QADAM 3: Rasmni qabul qilish -> Janrlarni so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_anime_photo, F.photo)
async def process_anime_photo(message: Message, state: FSMContext):
    # Eng sifatli rasm file_id'si
    photo_file_id = message.photo[-1].file_id
    
    await state.update_data(poster_id=photo_file_id)
    
    await state.set_state(AnimeMenuState.adding_genres)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_anime_panel"))
    
    # ✨ To'g'rilandi: reply_markup=builder.as_markup() qo'shildi, tugma ko'rinadi
    await message.reply(
        "📌 Endi anime **janrlarini** kiriting (masalan: Jangari, Komediya):",
        reply_markup=builder.as_markup()
    )




# =====================================================================
# QADAM 4: Janrlarni qabul qilish -> Yilni so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_genres)
async def process_anime_genres(message: Message, state: FSMContext):
    if not message.text:
        await message.reply("❌ Iltimos, faqat matnli xabar yuboring. Anime janrlarini kiriting:")
        return
    
    # Janrlarni ro'yxatga ajratish
    genres = [g.strip() for g in message.text.split(",") if g.strip()]
    
    # 💡 Kichik qo'shimcha: Agar admin to'g'ri janr kiritmagan bo'lsa (masalan: ", ,, ,")
    if not genres:
        await message.reply("⚠️ Janrlar aniqlanmadi. Iltimos, kamida bitta janr kiriting (masalan: _Jangari, Komediya_):")
        return
    
    await state.update_data(genres=genres)
    
    await state.set_state(AnimeMenuState.adding_year)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_anime_panel"))
    
    await message.reply(
        "📌 Endi anime **chiqarilgan yilini** kiriting (masalan: _2024_):",
        reply_markup=builder.as_markup()
    )



# =====================================================================
# QADAM 5: Yilni qabul qilish -> Tavsifni so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_year)
async def process_anime_year(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.reply("❌ Iltimos, faqat butun son kiriting (Masalan: `2025`):")
        return
    
    year_value = int(message.text.strip())
    
    # 💡 Kichik reallik tekshiruvi (Masalan, 1950 va 2030 yillar oralig'i)
    if year_value < 1950 or year_value > 2030:
        await message.reply("⚠️ Iltimos, real yilni kiriting (1950 - 2030 oralig'ida):")
        return
        
    await state.update_data(year=year_value)
    await state.set_state(AnimeMenuState.adding_description)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_anime_panel"))
    
    await message.reply(
        "📌 Endi anime **tavsifini (Description)** kiriting:",
        reply_markup=builder.as_markup()
    )


# =====================================================================
# QADAM 6: Tavsifni qabul qilish -> Tillarni so'rash
# =====================================================================
@router.message(AnimeMenuState.adding_description)
async def process_anime_description(message: Message, state: FSMContext):
    if not message.text:
        await message.reply("❌ Iltimos, faqat matnli xabar yuboring. Anime tavsifini kiriting:")
        return
    
    await state.update_data(description=message.text.strip())
    await state.set_state(AnimeMenuState.adding_laguages)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_anime_panel"))
    
    await message.reply(
        "📌 Endi anime **tillarini** kiriting (masalan: Yaponcha, Inglizcha):",
        reply_markup=builder.as_markup()
    )





# =====================================================================
# QADAM 7: Tillarni olish -> BAZAGA VA KESHGA YOZISH (YAKUN)
# =====================================================================
@router.message(AnimeMenuState.adding_laguages)
async def process_anime_languages_and_save(message: Message, state: FSMContext, session_pool: async_sessionmaker):
    if not message.text:
        await message.reply("❌ Iltimos, matn kiriting:")
        return

    await state.update_data(languages=message.text.strip())
    fsm_data = await state.get_data()
    loading_msg = await message.answer("🚀 Bazaga saqlanmoqda...")

    async with session_pool() as session:
        try:
            # 1. Bazaga qo'shish
            new_anime = await AnimeRepository.add_anime(
                session=session,
                title=fsm_data["title"],
                poster_id=fsm_data["poster_id"],
                year=fsm_data["year"],
                is_completed=False,
                genres=fsm_data["genres"],
                description=fsm_data["description"],
                languages=fsm_data["languages"],
                episodes=[]
            )
            
            # 2. Tugmachalar (Builder to'g'rilandi)
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(
                text="Qism qo'shishni boshlash", 
                callback_data=f"add_ep_{new_anime.anime_id}") # .anime_id ga o'zgartirildi
            )
            builder.row(types.InlineKeyboardButton(
                text="🔙 Admin Panelga qaytish", 
                callback_data="admin_anime_panel")
            )
            
            # 3. Muvaffaqiyatli yakunlash
            await loading_msg.edit_text(
                f"🎉 {new_anime.title} muvaffaqiyatli qo'shildi!", 
                reply_markup=builder.as_markup()
            )
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Xatolik: {e}")
            await loading_msg.edit_text("❌ Bazada xatolik. Iltimos, keyinroq urinib ko'ring.")
        
        finally:
            await state.clear()

# =====================================================================
# QADAM 8: Qism qo'shish jarayoni (Video qabul qilish va bazaga saqlash)
# =====================================================================
@router.callback_query(F.data.startswith("add_ep_"))
async def start_add_episode(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer()
    
    # callback_data dan anime_id ni olamiz ("add_ep_45" -> 45)
    anime_id = int(callback.data.split("_")[2])
    
    # 1. Bazadan ushbu animening joriy qismlarini tekshiramiz (Avto-qism uchun)
    anime = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    if not anime:
        await callback.message.answer("❌ Anime topilmadi.")
        return
        
    # Agarda epizodlar ro'yxati bo'lsa, uning uzunligiga 1 qo'shamiz (masalan: 0 bo'lsa 1-qism, 12 ta bo'lsa 13-qism)
    next_episode_number = len(anime.episodes) + 1 if anime.episodes else 1
    
    # 2. Ma'lumotlarni FSM xotirasiga saqlaymiz
    await state.update_data(anime_id=anime_id, episode_number=next_episode_number)
    
    # 3. To'g'ridan-to'g'ri video/fayl qabul qilish holatiga o'tkazamiz
    await state.set_state(AnimeMenuState.adding_episode_video) # State nomingizga moslang
    
    await callback.message.answer(
        f"🎬 **Anime:** {anime.title}\n"
        f"🔢 **Tizim aniqlagan qism:** {next_episode_number}-qism\n\n"
        f"📌 Iltimos, ushbu qismning **videosini** yoki **faylini (document)** yuboring:"
    )




# =====================================================================
# QADAM 9: Video yoki faylni qabul qilish -> Bazaga saqlash va keyingi qismni kutish
# =====================================================================
# ✅ F.video | F.document filtri orqali ikkala formatni ham ushlaymiz
@router.message(AnimeMenuState.adding_episode_video, F.video | F.document)
async def process_episode_video(message: Message, state: FSMContext, session: AsyncSession):
    video_file_id = None
    
    # 1. Video formatini tekshirish
    if message.video:
        video_file_id = message.video.file_id
    elif message.document:
        mime = message.document.mime_type
        if mime and not mime.startswith("video/"):
            await message.reply("⚠️ Iltimos, faqat video formatdagi fayl yuboring!")
            return
        video_file_id = message.document.file_id

    if not video_file_id:
        await message.reply("❌ Videoni aniqlab bo'lmadi, qaytadan yuboring:")
        return

    # FSM xotirasidan ma'lumotlarni olamiz
    data = await state.get_data()
    anime_id = data["anime_id"]
    ep_number = data["episode_number"]
    
    loading_msg = await message.answer(f"🚀 {ep_number}-qism bazaga qo'shilmoqda...")

    try:
        # 2. Bazaga epizodni qo'shamiz
        await AnimeRepository.add_episode(
            session=session,
            anime_id=anime_id,
            episode_number=ep_number,
            file_id=video_file_id
        )
        
        # 🔥 KEYINGI QISM UCHUN AVTOMATIK RAQAMNI OSHIRAMIZ (+1)
        next_ep = ep_number + 1
        await state.update_data(episode_number=next_ep)
        
        # 3. Tugmalar (Siz aytgan variant: Yakunlash va Kanalga yuborish mantiqi bilan)
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(
            text="📢 Kanalga e'lon qilish va tugatish", 
            callback_data=f"publish_anime_{anime_id}" # 👈 Kanalga yuborish tugmasi
        ))
        builder.row(types.InlineKeyboardButton(
            text="💾 Shunchaki saqlash va tugatish", 
            callback_data="finish_anime_add" # 👈 Kanalga yubormasdan yakunlash
        ))

        await loading_msg.edit_text(
            f"✅ **{ep_number}-qism muvaffaqiyatli saqlandi!**\n\n"
            f"💡 **Navbatdagi bosqich:** Hozir bot {next_ep}-qismni kutish rejimida.\n"
            f"Yana qismlar bo'lsa, **to'g'ridan-to'g'ri video yuborishda davom eting**.\n\n"
            f"Agar qismlar tugagan bo'lsa, pastdagi tugmalardan birini tanlang:",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"❌ Qismni saqlashda xatolik: {e}")
        await loading_msg.edit_text("❌ Xatolik yuz berdi. Qism bazaga saqlanmadi.")





# =====================================================================
# QADAM 10: Anime kanalga yuborish yoki shunchaki saqlash va yakunlash
# =====================================================================
@router.callback_query(F.data == "finish_anime_add")
async def finish_anime_addition(callback: CallbackQuery, state: FSMContext):
    await callback.answer("✅ Jarayon muvaffaqiyatli yakunlandi!")
    
    # 1. FSM xotirasini butunlay tozalaymiz
    await state.clear()
    
    # 2. Tugmani srazu inline tarzda yasaymiz
    panel_button = InlineKeyboardBuilder().row(
        types.InlineKeyboardButton(text="🔙 Admin Panelga qaytish", callback_data="admin_anime_panel")
    ).as_markup()
    
    # 3. Rasm/Video ostidagi matnni (caption) xavfsiz yangilaymiz va tugmani ulaymiz
    try:
        await callback.message.edit_caption(
            caption=(
                "🎉 **Barcha qismlar muvaffaqiyatli saqlandi!**\n"
                "Anime bazada tayyor, lekin kanalga yuborilmadi."
            ),
            reply_markup=panel_button
        )
    except TelegramBadRequest:
        # Agar tasodifan bu oddiy matnli xabar bo'lsa (rasmsiz), edit_text ga o'tadi
        await callback.message.edit_text(
            text=(
                "🎉 **Barcha qismlar muvaffaqiyatli saqlandi!**\n"
                "Anime bazada tayyor, lekin kanalga yuborilmadi."
            ),
            reply_markup=panel_button
        )




@router.callback_query(F.data.startswith("publish_anime_"))
async def publish_anime_to_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer("📢 Kanalga yuborilmoqda...")
    
    anime_id = int(callback.data.split("_")[2])
    
    # Bazadan animeni barcha ma'lumotlari bilan olamiz
    anime = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    
    if anime:
        try:
            # 📢 KANALGA POST SHABLONI
            caption = (
                f"🎬 **YANGI ANIME KANALGA JOYLANDI!**\n\n"
                f"📌 **Nomi:** {anime.title}\n"
                f"📅 **Yili:** {anime.year}\n"
                f"🎭 **Janrlari:** {', '.join(anime.genres) if anime.genres else 'Mavjud emas'}\n"
                f"🗣️ **Tili:** {anime.languages}\n\n"
                f"🍿 **Jami yuklangan qismlar soni:** {len(anime.episodes)} ta\n\n"
                f"🤖 Botimiz orqali tomosha qiling: @AninovuzBot" # Bot username'ingiz
            )
            
            # Kanalga rasm (Poster) va opisaniya yuboriladi
            await callback.bot.send_photo(
                chat_id="@Aninovuz", 
                photo=anime.poster_id,
                caption=caption
            )
            
            # 🔙 Admin panelga qaytish tugmasini yasaymiz
            builder = InlineKeyboardBuilder() # To'g'ri nomlandi
            builder.row(types.InlineKeyboardButton(
                text="🔙 Admin Panelga qaytish", 
                callback_data="admin_anime_panel"
            ))
            
            # ✨ To'g'rilandi: Rasm xabari bo'lgani uchun edit_caption ishlatamiz va reply_markup ulaymiz
            await callback.message.edit_caption(
                caption="🚀 **Anime muvaffaqiyatli saqlandi va @Aninovuz kanaliga e'lon qilindi!**",
                reply_markup=builder.as_markup() # Tugma ulandi!
            )
            
        except Exception as e:
            logger.error(f"❌ Kanalga yuborishda xato: {e}")
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
            
            await callback.message.edit_caption(
                caption="✅ **Bazaga saqlandi, lekin kanalga yuborishda xatolik bo'ldi!**\n(Bot kanalda admin ekanligini va ruxsatlari borligini tekshiring).",
                reply_markup=builder.as_markup()
            )
    else:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        await callback.message.edit_caption(caption="❌ Xatolik: Anime topilmadi.", reply_markup=builder.as_markup())

    # 🔥 FSM tozalanadi va admin erkin holatga qaytadi
    await state.clear()










@router.callback_query(AnimePageCallback.filter())  # Sahifalar almashganda ushlab qolish uchun
@router.callback_query(F.data == "list_anime")
async def list_anime(callback: CallbackQuery, session: AsyncSession = None, session_pool: async_sessionmaker = None):
    await callback.answer("📋 Yuklanmoqda...")
    
    # 💡 AGAR MIDDLEWARE'DAN SESSION 'NONE' KELSA, POOLDAN YANGI SESSYA OCHAMIZ
    if session is None and session_pool is not None:
        async with session_pool() as new_session:
            anime_list = await AnimeRepository.list_anime(session=new_session)
    else:
        # Oddiy holatda uzatilgan sessiyadan foydalanamiz
        anime_list = await AnimeRepository.list_anime(session=session)

    if not anime_list:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))
        await callback.message.edit_text(
            "📭 Hozircha tizimda birorta ham anime qo'shilmagan.", 
            reply_markup=builder.as_markup()
        )
        return
    
    # 3. Pagination sozlamalari (Har bir sahifada 5 tadan anime)
    PER_PAGE = 5
    total_anime = len(anime_list)
    total_pages = (total_anime + PER_PAGE - 1) // PER_PAGE
    
    # Sahifa chegaradan chiqib ketmasligi tekshiruvi
    page = max(1, min(page, total_pages))
    
    # Joriy sahifaga tegishli animelarni kesib olish (Slice)
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_anime = anime_list[start_idx:end_idx]
    
    # 4. Tugmalarni yig'ish (InlineKeyboardBuilder)
    builder = InlineKeyboardBuilder()
    
    for anime in page_anime:
        # Masalan: is_completed True bo'lsa "🟢 Tugallangan", False bo'lsa "🔴 Davom etyapti"
        status = "🟢" if anime.is_completed else "🔴" 
        text = f"{status} {anime.title} ({anime.year})"
        
        # Har bir animeni alohida qator qilib tugma sifatida qo'shamiz
        builder.row(
            types.InlineKeyboardButton(
                text=text,
                callback_data=AnimeDetailCallback(
                    anime_id=int(anime.anime_id), 
                    page=page
                ).pack()
            )
        )
    
    # 5. Navigatsiya (Orqaga/Oldinga) tugmalari
    nav_buttons = []
    
    # Oldingi sahifa tugmasi
    if page > 1:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="⬅️ Oldingi", 
                callback_data=AnimePageCallback(page=page - 1).pack()
            )
        )
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="❌", callback_data="noop"))
        
    # Joriy sahifa ko'rsatkichi
    nav_buttons.append(
        types.InlineKeyboardButton(
            text=f"📄 {page}/{total_pages}", 
            callback_data="noop"
        )
    )
    
    # Keyingi sahifa tugmasi
    if page < total_pages:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="Keyingi ➡️", 
                callback_data=AnimePageCallback(page=page + 1).pack()
            )
        )
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="❌", callback_data="noop"))
        
    builder.row(*nav_buttons)
    
    # 6. Eng pastdagi doimiy "Orqaga" tugmasi (Admin panelga qaytish)
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_anime_panel"))
    
    # Xabarni yangilash (edit_text) orqali inline tugmalarni ko'rsatamiz
    await callback.message.edit_text(
        text=f"📋 <b>ANIMELAR RO'YXATI (Jami: {total_anime} ta)</b>\n\n"
             f"<i>Kerakli animeni tanlab, ustiga bosing:</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )






@router.callback_query(AnimeDetailCallback.filter())
async def show_anime_details(callback: CallbackQuery, callback_data: AnimeDetailCallback, session: AsyncSession):
    await callback.answer("📖 Ma'lumotlar yuklanmoqda...")
    
    anime_id = callback_data.anime_id
    current_page = callback_data.page  # Orqaga qaytganimizda aynan o'sha sahifaga qaytish uchun
    
    # 1. Animeni barcha munosabatlari (janrlari) bilan birga bazadan olamiz
    stmt = (
        select(Anime)
        .options(selectinload(Anime.genres))
        .where(Anime.anime_id == anime_id)
    )
    result = await session.execute(stmt)
    anime = result.scalar_one_or_none()
    
    if not anime:
        await callback.message.edit_text("❌ Kechirasiz, ushbu anime topilmadi.")
        return

    # 2. Janrlarni chiroyli matn holatiga keltiramiz
    genres_str = ", ".join([g.name for g in anime.genres]) if anime.genres else "Mavjud emas"
    status_str = "🟢 Tugallangan" if anime.is_completed else "🔴 Davom etmoqda"

    # 3. Anime haqida to'liq ma'lumot matni
    text = (
        f"🎬 <b>ANIME TAFIYOLATLARI</b>\n\n"
        f"📌 <b>Nomi:</b> {anime.title}\n"
        f"📅 <b>Yili:</b> {anime.year}-yil\n"
        f"🚦 <b>Status:</b> {status_str}\n"
        f"🌐 <b>Tillar:</b> {anime.languages or 'Koʻrsatilmagan'}\n"
        f"🎭 <b>Janrlar:</b> {genres_str}\n\n"
        f"📝 <b>Ta'rif:</b>\n<i>{anime.description or 'Taʻrif mavjud emas.'}</i>"
    )

    # 4. Inline tugmalarni yig'ish
    builder = InlineKeyboardBuilder()
    
    # 🔥 SHU JOYIDAN QISM QO'SHISH TUGMASI
    # Callback_data ichiga anime_id ni berib yuboramiz, keyingi bosqichda as qotadi
    builder.row(
        types.InlineKeyboardButton(
            text="➕ Ushbu animega qism qo'shish", 
            callback_data=f"add_ep_{anime.anime_id}"
        )
    )
    
    # 🔙 ORQAGA TUGMASI
    # Foydalanuvchi adashib ketmasligi uchun aynan o'zi kelgan sahifa (page) raqamiga qaytaramiz
    builder.row(
        types.InlineKeyboardButton(
            text="🔙 Ro'yxatga qaytish", 
            callback_data=AnimePageCallback(page=current_page).pack()
        )
    )

    # Agar anime posteri (rasmi) bo'lsa rasmi bilan, bo'lmasa oddiy matn qilib chiqarish
    if anime.poster_id:
        try:
            # Agar rasm bo'lsa, xabarni o'chirib yangi rasm ko'rinishida yuboramiz
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=anime.poster_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
        except Exception:
            # Agar rasm o'chib ketgan bo'lsa, matn o'zini edit qilamiz
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())