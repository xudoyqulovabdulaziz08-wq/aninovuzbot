import os
import asyncio
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)
from sqlalchemy import text
from config import config

logger = logging.getLogger("DB")

# ================= ENGINE (POSTGRESQL ULANISH) =================
# 🚀 Render va PostgreSQL uchun optimallashtirilgan ulanish tizimi

engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,

    # Sessiyalar limitidan oshib ketmaslik uchun config'dan olyapmiz:
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,

    # Zombie ulanishlarni o'ldirish va qayta tiklash
    pool_pre_ping=True,
    pool_recycle=900,  # Ulanishlarni har 15 daqiqada yangilash
    pool_timeout=15,   # Puldan joy bo'shashini kutish vaqti

    # ✅ FIX: PostgreSQL-da 'wallet_location' kerak emasligi uchun connect_args bo'shatildi yoki mTLS shart bo'lsa ssl parametrlarini yozish mumkin
    connect_args={}
)

# ================= SESSION =================
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ================= HEALTH CHECK =================
async def check_db(retries: int = 3, delay: float = 2.0):
    """
    Bot ishga tushayotganda PostgreSQL bazasini tekshirish (Standart SELECT 1 orqali)
    """
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                # ✅ FIX: Oracle uchun xos bo'lgan "FROM dual" olib tashlandi, PostgreSQL uchun toza "SELECT 1" qo'yildi
                await conn.execute(text("SELECT 1"))

            logger.info("🚀 PostgreSQL Database connected successfully and healthy!")
            return True

        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL DB check failed ({attempt}/{retries}): {e}")

            if attempt == retries:
                logger.critical("🚨 DATABASE DEAD - CANNOT START APPLICATION")
                return False

            await asyncio.sleep(delay)

# ================= SAFE EXECUTOR =================
async def safe_db_execute(session: AsyncSession, stmt, timeout: float = 3.0):
    """
    🔥 So'rovlar osilib qolishini oldini oluvchi xavfsiz executor wrapper.
    """
    try:
        async with asyncio.timeout(timeout):
            return await session.execute(stmt)
    except asyncio.TimeoutError:
        logger.error(f"⏱ DB query timeout (>{timeout}s) on execution!")
        raise
    except Exception as e:
        logger.error(f"❌ DB execute error: {e}")
        raise

# ================= GRACEFUL SHUTDOWN =================
async def close_db():
    """
    Bot to'xtatilganda barcha ulanishlar pulini toza yopish
    """
    try:
        await engine.dispose()
        logger.info("🛑 PostgreSQL DB engine connection pool closed gracefully")
    except Exception as e:
        logger.error(f"Error closing DB pool: {e}")