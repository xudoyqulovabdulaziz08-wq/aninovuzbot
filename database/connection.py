import os
import ssl
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

# ================= SSL CONFIG =================
def get_ssl_context():
    """
    Aiven Cloud va boshqa xavfsiz bazalar uchun SSLContext yaratish.
    asyncpg drayveri standart ssl.SSLContext obyektini qo'llab-quvvatlaydi,
    lekin connect_args ichida "ssl" kaliti bilan uzatilishi kerak.
    """
    if not getattr(config, "DB_SSL", False):
        return None

    try:
        ca_path = os.path.join(ROOT_DIR, "ca.pem")
        
        # Sertifikat mavjudligini tekshirish
        if not os.path.exists(ca_path):
            logger.error(f"❌ SSL ca.pem file not found at: {ca_path}")
            return None

        ssl_context = ssl.create_default_context(cafile=ca_path)
        # Ba'zi self-signed (o'zi imzolagan) sertifikatlar uchun tekshirishni yumshatish (Aiven uchun tavsiya etiladi)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        logger.info("🔒 SSL Context successfully initialized for DB")
        return ssl_context
    except Exception as e:
        logger.warning(f"⚠️ SSL init failed, fallback to non-SSL: {e}")
        return None


ssl_context = get_ssl_context()

# ================= ENGINE =================
# Engine yaratish qismida connect_args ni asyncpg drayveriga to'g'ri uzatamiz
connect_args = {}
if ssl_context:
    connect_args["ssl"] = ssl_context
else:
    # Agarda SSL o'chiq bo'lsa, lekin URL tarkibida sslmode so'ralsa fallback
    connect_args["server_settings"] = {"jit": "off"} # Render kichik serverlari uchun CPU tejash

engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,

    # 🔥 Render / Aiven kichik paketlari (Hobby/Startup) uchun mukammal ulanishlar puli
    pool_size=20,
    max_overflow=10,

    # Zombie ulanishlarni o'ldirish va qayta tiklash (Aiven drop connection fix)
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=15,  # Ulanish kutish vaqtini 15 soniyaga bir oz oshirdik (High load uchun xavfsiz)

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
    Bot ishga tushayotganda bazani tekshirish (Retry mexanizmi bilan)
    """
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            logger.info("🚀 PostgreSQL connected successfully and healthy!")
            return True

        except Exception as e:
            logger.warning(f"⚠️ DB check failed ({attempt}/{retries}): {e}")

            if attempt == retries:
                logger.critical("🚨 DATABASE DEAD - CANNOT START APPLICATION")
                return False

            await asyncio.sleep(delay)


# ================= SAFE EXECUTOR =================
async def safe_db_execute(session: AsyncSession, stmt, timeout: float = 3.0):
    """
    🔥 So'rovlar osilib qolishini oldini oluvchi xavfsiz executor wrapper.
    Kichik serverlarda o'ta og'ir so'rovlarni vaqtida to'xtatadi.
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
    Bot to'xtatilganda barcha ulanishlar pulini toza yopish (Graceful Shutdown)
    """
    try:
        await engine.dispose()
        logger.info("🛑 DB engine connection pool closed gracefully")
    except Exception as e:
        logger.error(f"Error closing DB pool: {e}")