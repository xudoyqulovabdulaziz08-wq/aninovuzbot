import logging
import html
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
    
    updating_anime = State()

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
# QADAM 1: Anime qo'shish boshlanishi
# =====================================================================
@router.callback_query(F.data == "AnimeMenuCallbacks.ADD_ANIME")
async def admin_add(callback: CallbackQuery, state: FSMContext):
    # 1. Bir marta va aniq javob beramiz
    await callback.answer("📌 Yangi anime qo'shish jarayoni boshlandi!")
    
    # 2. Holatni (State) o'rnatamiz
    await state.set_state(AnimeMenuState.adding_anime_name)
    
    # 3. Tugmalarni to'g'ri yig'amiz
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="add_anime_main"))
    
    # 4. Matndagi formatlashni HTML rejimiga moslaymiz
    text = (
        "🎬 <b>Yangi anime qo'shish jarayoni</b>\n\n"
        "📌 Iltimos, yangi anime nomini kiriting:"
    )
    
    try:
        # 🔥 FIX: reply_markup uchun builder.as_markup() uzatiladi
        await callback.message.edit_text(
            text=text, 
            reply_markup=builder.as_markup(), 
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        # Agar xabar o'zgarmagan bo'lsa xatolikni yutib yuboramiz, boshqalarini log qilamiz
        if "message is not modified" not in str(e).lower():
            logger.error(f"❌ Anime panel xatosi: {e}")




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
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="add_anime_main"))
    
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
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="add_anime_main"))
    
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
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="add_anime_main"))
    
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
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="add_anime_main"))
    
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
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="add_anime_main"))
    
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
                callback_data="add_anime_main")
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
    
    # 1. Bazadan ushbu animening joriy qismlarini tekshiramiz
    anime = await AnimeRepository.get_anime_by_id(session=session, anime_id=anime_id)
    if not anime:
        await callback.message.answer("❌ Anime topilmadi.")
        return
        
    # 🔥 CRITICAL FIX: anime obyekti 'dict' yoki 'Model' ekanligini tekshirib, xavfsiz qismlar sonini aniqlaymiz
    if isinstance(anime, dict):
        # Agar dict kelsa, ichidan 'episodes' kalitini yoki 'title'ni dict ko'rinishida olamiz
        episodes_list = anime.get("episodes", [])
        anime_title = anime.get("title", "Unknown")
    else:
        # Agar ORM Model bo'lsa, atribut sifatida olamiz
        episodes_list = getattr(anime, "episodes", []) or []
        anime_title = getattr(anime, "title", "Unknown")

    # Qismlar soniga qarab navbatdagi qism raqamini hisoblaymiz
    next_episode_number = len(episodes_list) + 1 if episodes_list else 1
    
    # 2. Ma'lumotlarni FSM xotirasiga saqlaymiz
    await state.update_data(anime_id=anime_id, episode_number=next_episode_number)
    
    # 3. To'g'ridan-to'g'ri video/fayl qabul qilish holatiga o'tkazamiz
    await state.set_state(AnimeMenuState.adding_episode_video)
    
    # UX FIX: Matn uslubini HTML formatga moslashtirdik
    await callback.message.answer(
        f"🎬 <b>Anime:</b> {anime_title}\n"
        f"🔢 <b>Tizim aniqlagan qism:</b> {next_episode_number}-qism\n\n"
        f"📌 Iltimos, ushbu qismning <b>videosini</b> yoki <b>faylini (document)</b> yuboring:",
        parse_mode="HTML"
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
        await AnimeRepository.add_anime_episode(
            session=session,
            anime_id=anime_id,
            episode_num=ep_number,  # 🔥 MANA SHU YER FIX BOLDId: episode_number emas, episode_num bo'lishi shart!
            file_id=video_file_id
        )
        
        # 🔥 KEYINGI QISM UCHUN AVTOMATIK RAQAMNI OSHIRAMIZ (+1)
        next_ep = ep_number + 1
        await state.update_data(episode_number=next_ep)
        
        # 3. Tugmalarni yig'ish
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(
            text="📢 Kanalga e'lon qilish va tugatish", 
            callback_data=f"publish_anime_{anime_id}"
        ))
        builder.row(types.InlineKeyboardButton(
            text="💾 Shunchaki saqlash va tugatish", 
            callback_data="finish_anime_add"
        ))

        # UX FIX: <blockquote expandable> yordamida ko'p qismli yuklashni juda qulay qildik
        await loading_msg.edit_text(
            f"✅ <b>{ep_number}-qism muvaffaqiyatli saqlandi!</b>\n\n"
            f"💡 <b>Navbatdagi bosqich:</b> Bot hozir avtomat ravishda <code>{next_ep}-qism</code>ni kutmoqda.\n"
            f"<blockquote expandable>"
            f"Yana seriyalar bo'lsa, hech narsani bosmasdan <b>to'g'ridan-to'g'ri video yuborishda davom eting</b>.\n"
            f"Barcha qismlar tugagan bo'lsa, pastdagi yakunlovchi tugmalardan birini tanlang:"
            f"</blockquote>",
            parse_mode="HTML",
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
    
    # 1. FSM xotirasini butunlay tozalaymiz (Admin erkin holatga qaytadi)
    await state.clear()
    
    # 2. Tugmani ixcham va toza tarzda yasaymiz
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Admin Panelga qaytish", callback_data="admin_anime_panel"))
    panel_button = builder.as_markup()
    
    # Chiqadigan chiroyli matn shabloni (HTML formatida)
    text_content = (
        "🎉 <b>Barcha qismlar muvaffaqiyatli saqlandi!</b>\n\n"
        "<i>Anime ma'lumotlar bazasida tayyor, lekin kanalga e'lon qilinmadi.</i>"
    )
    
    # 3. Rasm ostidagi matnni (caption) yoki oddiy matnni xavfsiz yangilaymiz
    try:
        await callback.message.edit_caption(
            caption=text_content,
            parse_mode="HTML",  # 🔥 FIX: Matn chiroyli chiqishi uchun parse_mode qo'shildi
            reply_markup=panel_button
        )
    except TelegramBadRequest as e:
        # Agar oldingi xabar rasmsiz (toza matnli) bo'lsa, edit_text ishlaydi
        if "message is not modified" not in str(e).lower():
            try:
                await callback.message.edit_text(
                    text=text_content,
                    parse_mode="HTML",  # 🔥 FIX: parse_mode qo'shildi
                    reply_markup=panel_button
                )
            except TelegramBadRequest:
                # Agar biron sabab bilan edit qilib bo'lmasa, yangi xabar yuboramiz
                await callback.message.answer(
                    text=text_content,
                    parse_mode="HTML",
                    reply_markup=panel_button
                )


# =====================================================================
# QADAM 10: Anime kanalga yuborish yoki shunchaki saqlash va yakunlash
# =====================================================================
@router.callback_query(F.data.startswith("publish_anime_"))
async def publish_anime_to_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer("📢 Kanalga yuborilmoqda...")
    
    # Callback data ichidan xavfsiz ID ni ajratib olamiz
    anime_id = int(callback.data.split("_")[2])
    
    # 1. Animeni barcha munosabatlari (janrlari) bilan birga bazadan bitta so'rovda olamiz
    stmt = (
        select(Anime)
        .options(selectinload(Anime.genres))
        .where(Anime.anime_id == anime_id)
    )
    result = await session.execute(stmt)
    anime = result.scalar_one_or_none()
    
    # 2. Agar anime topilmasa, jarayonni to'xtatamiz
    if not anime:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_anime_panel"))
        
        try:
            await callback.message.edit_caption(caption="❌ Kechirasiz, ushbu anime topilmadi.", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            await callback.message.edit_text("❌ Kechirasiz, us'hbu anime topilmadi.", reply_markup=builder.as_markup())
        return

    # 3. Ma'lumotlarni xavfsiz formatlaymiz (Faqat baza obyektidan so'ng!)
    genres_str = ", ".join([g.name for g in anime.genres]) if anime.genres else "Mavjud emas"
    status_str = "🟢 Tugallangan" if anime.is_completed else "🔴 Davom etmoqda"
    
    safe_title = html.escape(anime.title)
    safe_description = html.escape(anime.description or 'Description unavailable.')

    # 4. 📢 KANALGA POST SHABLONI
    caption = (
        f"╔══════════════════╗\n"
        f"       🎬 <b>{safe_title}</b>\n"
        f"╚══════════════════╝\n\n"

        f"📌 <b>Anime Info</b>\n"
        f"╔══════════════════╗\n"
        f"├ 🆔 ID: <code>#{anime.anime_id}</code>\n"  
        f"├ 📅 Year: <b>{anime.year}</b>\n"
        f"├ 🚦 Status: <b>{status_str}</b>\n"
        f"├ 🌐 Lang: <b>{anime.languages or 'Unknown'}</b>\n"
        f"╚══════════════════╝\n"
        f"╔══════════════════╗\n"
        f"└ 🎭 Genres: <b>{genres_str}</b>\n\n"
        f"╚══════════════════╝\n\n"
        f"📝 <b>Tavsif</b>\n"
        f"<blockquote expandable>"
        f"{safe_description}"
        f"</blockquote>"
    )
    
    # Admin panelga qaytish tugmasi
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🔙 Admin Panelga qaytish", 
        callback_data="admin_anime_panel"
    ))
    markup = builder.as_markup()

    try:
        # 5. Kanalga rasm (Poster) va opisaniya yuboriladi
        await callback.bot.send_photo(
            chat_id="@Aninovuz", 
            photo=anime.poster_id,
            caption=caption,
            parse_mode="HTML"  # 🔥 FIX: Teglar ishlashi uchun parse_mode shart!
        )
        
        # Admin xabarini yangilaymiz
        await callback.message.edit_caption(
            caption="🚀 <b>Anime muvaffaqiyatli saqlandi va @Aninovuz kanaliga e'lon qilindi!</b>",
            parse_mode="HTML",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"❌ Kanalga yuborishda xato: {e}")
        
        # Kanalga yuborishda muammo bo'lsa, adminni ogohlantiramiz, lekin bazada anime baribir qoladi
        await callback.message.edit_caption(
            caption="✅ <b>Bazaga saqlandi, lekin kanalga yuborishda xatolik bo'ldi!</b>\n"
                    "(Bot kanalda admin ekanligini va ruxsatlari borligini tekshiring).",
            parse_mode="HTML",
            reply_markup=markup
        )
    finally:
        # 🔥 FSM tozalanadi va admin holati tiklanadi
        await state.clear()