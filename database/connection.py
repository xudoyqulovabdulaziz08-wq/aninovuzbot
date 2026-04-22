from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import config

# ✅ URL .env faylidan olinadi
engine = create_async_engine(
    config.DATABASE_URL,
    connect_args={"ssl": True}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def check_db():
    try:
        async with engine.connect() as conn:
            print("✅ PostgreSQL bazasiga muvaffaqiyatli ulanildi!")
    except Exception as e:
        print(f"❌ Bazaga ulanishda xato: {e}")