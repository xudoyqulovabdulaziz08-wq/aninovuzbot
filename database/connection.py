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

# ❌ ESKI ORACLE CONFIG (WALLET / CERTS) FUNKSIYASINI BUTUNLAY OʻCHIRDIK!
# Chunki tunnel orqali mTLS (Wallet)'siz, toʻgʻridan-toʻgʻri TCP ulanamiz.

# ================= ENGINE (MAX CONNECTION 30 LIMIT FIX) =================
engine = create_async_engine(
    config.DATABASE_URL,  # Render'dagi: oracle+oracledb://ADMIN:parol@db.aninov.uz:1522/?service_name=aninovuzdb_high
    echo=False,

    # ⚠ Oracle Free Tier 30 ta sessiya limitidan oshib ketmaslik uchun:
    pool_size=10,
    max_overflow=5,

    # Zombie ulanishlarni o'ldirish va qayta tiklash
    pool_pre_ping=True,
    pool_recycle=900,  # Oracle ulanishlarni tezroq tozalashi uchun 15 daqiqaga tushirdik
    pool_timeout=15,   # Puldan joy bo'shashini kutish vaqti

    # 🔥 DIQQAT: connect_args ichidagi wallet va certs parametrlarini olib tashladik!
    # Drayver toza Thin mode rejimida internet orqali ulanib ketadi.
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
    Bot ishga tushayotganda Oracle bazasini tekshirish (DUAL jadvali orqali)
    """
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                # ⚠ Oracle'da oddiy "SELECT 1" xato beradi, "FROM dual" shart!
                await conn.execute(text("SELECT 1 FROM dual"))

            logger.info("🚀 Oracle Database connected successfully via Tunnel and healthy!")
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