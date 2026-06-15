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

# ================= ENGINE (WALLET ORQALI ULANISH) =================
# 🔐 Render Secret Files orqali mTLS (Wallet) bilan xavfsiz ulanish

engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,

    # ⚠ Oracle Free Tier 30 ta sessiya limitidan oshib ketmaslik uchun config'dan olyapmiz:
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,

    # Zombie ulanishlarni o'ldirish va qayta tiklash
    pool_pre_ping=True,
    pool_recycle=900,  # Oracle ulanishlarni tezroq tozalashi uchun 15 daqiqa
    pool_timeout=15,   # Puldan joy bo'shashini kutish vaqti

    # 🔥 DIQQAT: Config.py dan olingan Wallet parollari shu yerdan drayverga uzatiladi
    connect_args={
        "wallet_location": config.WALLET_LOCATION,
        "wallet_password": config.WALLET_PASSWORD
    }
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
    Bot ishga tushayotganda Oracle bazasini tekshirish (DUAL jadvali orqali)
    """
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                # ⚠ Oracle'da oddiy "SELECT 1" xato beradi, "FROM dual" shart!
                await conn.execute(text("SELECT 1 FROM dual"))

            logger.info("🚀 Oracle Database connected successfully via Wallet and healthy!")
            return True

        except Exception as e:
            logger.warning(f"⚠️ Oracle DB check failed ({attempt}/{retries}): {e}")

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
        logger.info("🛑 Oracle DB engine connection pool closed gracefully")
    except Exception as e:
        logger.error(f"Error closing DB pool: {e}")