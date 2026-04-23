import os
from pathlib import Path

import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import config
from sqlalchemy import text



ROOT_DIR = Path(__file__).resolve().parent.parent

ssl_context = ssl.create_default_context(
    cafile=os.path.join(ROOT_DIR, "ca.pem")
)

#ssl_context.load_cert_chain(
#   certfile=os.path.join(ROOT_DIR, "service.cert"),
#  keyfile=os.path.join(ROOT_DIR, "service.key")
#

# 2. Engine yaratishda "True" o'rniga shu ssl_context ni beramiz
engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,  # 🔥 connection eskirmasligi uchun
    connect_args={"ssl": ssl_context}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def check_db():
    try:
        # 'begin' orqali ulanish va tranzaksiyani avtomatik yopishni ta'minlaymiz
        async with engine.begin() as conn:
            await conn.scalar(text("SELECT 1"))
        print("✅ PostgreSQL bazasiga muvaffaqiyatli ulanildi!")
    except Exception as e:
        print(f"❌ Bazaga ulanishda xato: {e}")