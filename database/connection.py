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

ROOT_DIR = Path(__file__).resolve().parent.parent

# ================= ORACLE CONFIG (WALLET / CERTS) =================
def get_oracle_connect_args() -> dict:
    """
    Oracle Cloud Wallet (certs) papkasini Linux/Windows muhitiga moslab dynamic ulash.
    """
    # config.py ichida certs papkasi yo'li berilgan bo'lsa o'shani oladi, 
    # bo'lmasa loyiha ildizidagi 'certs' papkasini qidiradi
    certs_dir = getattr(config, "ORACLE_CERTS_DIR", os.path.join(ROOT_DIR, "certs"))
    
    # Render'da muhit o'zgaruvchisidan WALLET_PASSPHRASE ni o'qiymiz
    wallet_password = os.getenv("WALLET_PASSPHRASE")

    logger.info(f"--> Oracle config_dir ulanmoqda: {certs_dir}")

    # async oracledb Thin rejimida ishlashi uchun kerakli argumentlar
    connect_args = {
        "config_dir": certs_dir,
        "wallet_location": certs_dir,
    }
    
    if wallet_password:
        connect_args["wallet_password"] = wallet_password

    return connect_args

connect_args = get_oracle_connect_args()

# ================= ENGINE (MAX CONNECTION 30 LIMIT FIX) =================
engine = create_async_engine(
    config.DATABASE_URL,  # Bu yerda endi oracle+oracledb://... bo'lishi shart
    echo=False,

    # ⚠ Oracle Free Tier 30 ta sessiya limitidan oshib ketmaslik uchun:
    # pool_size va max_overflow jami 12 tadan oshmaydi. Bot yuqori yuklamada ham xavfsiz ishlaydi.
    pool_size=8,
    max_overflow=4,

    # Zombie ulanishlarni o'ldirish va qayta tiklash
    pool_pre_ping=True,
    pool_recycle=900,  # Oracle ulanishlarni tezroq tozalashi uchun 15 daqiqaga tushirdik
    pool_timeout=15,   # Puldan joy bo'shashini kutish vaqti

    connect_args=connect_args
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

            logger.info("🚀 Oracle Database connected successfully and healthy!")
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
    Bot to'xtatilganda barcha ulanishlar pulini toza yopish (Sessiyalar osilib qolmasligi uchun juda muhim!)
    """
    try:
        await engine.dispose()
        logger.info("🛑 Oracle DB engine connection pool closed gracefully")
    except Exception as e:
        logger.error(f"Error closing DB pool: {e}")