from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# PostgreSQL URL manzilingiz (asyncpg drayveri bilan)
# DIQQAT: 'postgresql://' ni 'postgresql+asyncpg://' ga o'zgartirdik
DATABASE_URL = "postgresql+asyncpg://avnadmin:AVNS_NL2rxYz4-DWFJ0f4Fme@pg-32706ea0-xudoyqulovabdulaziz08-0be3.h.aivencloud.com:27624/defaultdb?sslmode=require"

# 1. Engine yaratish (Bazaga ulanish yo'lagi)
engine = create_async_engine(
    DATABASE_URL,
    echo=False, # Loglarda har bir SQL so'rovni ko'rmaslik uchun False
    future=True
)

# 2. Sessionmaker yaratish (Har bir xabar uchun alohida sessiya ochish uchun)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 3. Bazaga ulanishni tekshirish funksiyasi (ixtiyoriy)
async def check_db():
    try:
        async with engine.connect() as conn:
            print("✅ PostgreSQL bazasiga muvaffaqiyatli ulanildi!")
    except Exception as e:
        print(f"❌ Bazaga ulanishda xato: {e}")