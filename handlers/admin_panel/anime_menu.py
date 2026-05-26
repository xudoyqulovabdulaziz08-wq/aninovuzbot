import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest



from config import config
from keyboards.inline import anime_menu_kb
from database.repository import AnimeRepository
from database.connection import AsyncSession

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
    add_episode = State()
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
@router.callback_query(F.data == AnimeMenuCallbacks.ADD_ANIME)
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
async def process_anime_languages_and_save(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text:
        await message.reply("❌ Iltimos, faqat matnli xabar yuboring. Anime tillarini kiriting:")
        return

    # 1. Tillarni xotiraga yozamiz
    await state.update_data(languages=message.text.strip())
    
    # 2. FSM xotirasidagi barcha ma'lumotlarni olamiz
    data = await state.get_data()
    
    # Yuklanish xabari
    loading_msg = await message.answer("🚀 Ma'lumotlar bazaga saqlanmoqda, iltimos kuting...")
    
    try:
        # 3. Bazaga saqlaymiz
        new_anime = await AnimeRepository.add_anime(
            session=session,
            title=data["title"],
            poster_id=data["poster_id"],
            year=data["year"],
            is_completed=False,
            genres=data["genres"],
            description=data["description"],
            languages=data["languages"],
            episodes=[]
        )
        
        # 4. Tugmalarni yasaymiz
        builder = InlineKeyboardBuilder()
        
        # 🔥 Dynamic Callback Data: Keyingi handlerda qaysi animega qism 
        # qo'shilayotganini bilish uchun ID'ni yuboramiz (masalan: add_episode:45)
        builder.row(types.InlineKeyboardButton(
            text="➕ Qism qo'shishni boshlash", 
            callback_data=f"add_ep_{new_anime.anime_id}" # Dynamic ID yuborildi
        ))
        builder.row(types.InlineKeyboardButton(
            text="🔙 Admin Panelga qaytish", 
            callback_data="admin_anime_panel"
        ))
        
        # 5. Muvaffaqiyatli xabar va tugmalarni yuborish
        await loading_msg.edit_text(
            f"🎉 **Yangi anime muvaffaqiyatli qo'shildi!**\n\n"
            f"🎬 **Nomi:** {new_anime.title}\n"
            f"📅 **Yili:** {new_anime.year}\n"
            f"🎭 **Janrlari:** {', '.join(data['genres'])}\n"
            f"🆔 **ID:** `{new_anime.anime_id}`\n\n"
            f"🔥 Valkey/Redis kesh tizimi avtomatik tarzda yangilandi!",
            reply_markup=builder.as_markup() # ✨ Mana shu yerda tugmalar ulandi!
        )
        
    except Exception as e:
        logger.error(f"❌ Animeni bazaga saqlashda xatolik: {e}")
        await loading_msg.edit_text("❌ Tizimda xatolik yuz berdi. Ma'lumotlar bazaga saqlanmadi.")
        
    finally:
        # 6. Jarayon tugadi, FSM tozalanadi
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


