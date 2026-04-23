import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import config

# 1. SSL sertifikatini tekshirishni chetlab o'tish uchun kontekst yaratamiz
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# 2. Engine yaratishda "True" o'rniga shu ssl_context ni beramiz
engine = create_async_engine(
    config.DATABASE_URL,
    connect_args={"ssl": ssl_context}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def check_db():
    try:
        async with engine.connect() as conn:
            # Oddiygina SELECT 1 so'rovini bajarib ko'ramiz
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
            print("✅ PostgreSQL bazasiga muvaffaqiyatli ulanildi!")
    except Exception as e:
        print(f"❌ Bazaga ulanishda xato: {e}")