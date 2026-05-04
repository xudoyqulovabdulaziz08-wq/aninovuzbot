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
    if not getattr(config, "DB_SSL", False):
        return None

    try:
        ssl_context = ssl.create_default_context(
            cafile=os.path.join(ROOT_DIR, "ca.pem")
        )
        return ssl_context
    except Exception as e:
        logger.warning(f"SSL init failed, fallback to non-SSL: {e}")
        return None


ssl_context = get_ssl_context()

# ================= ENGINE =================
engine = create_async_engine(
    config.DATABASE_URL,

    echo=False,

    # 🔥 Render / small server uchun optimal
    pool_size=5,
    max_overflow=10,

    pool_pre_ping=True,
    pool_recycle=1800,

    # 🔥 timeoutlar
    pool_timeout=10,

    connect_args={
        "ssl": ssl_context
    } if ssl_context else {}
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
    DB health check with retry logic
    """
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            logger.info("✅ PostgreSQL connected")
            return True

        except Exception as e:
            logger.warning(f"DB check failed ({attempt}/{retries}): {e}")

            if attempt == retries:
                logger.critical("❌ DATABASE DEAD")
                return False

            await asyncio.sleep(delay)


# ================= SAFE EXECUTOR =================
async def safe_db_execute(session: AsyncSession, stmt, timeout: float = 2.5):
    """
    🔥 Query timeout wrapper (VERY IMPORTANT)
    """
    try:
        async with asyncio.timeout(timeout):
            return await session.execute(stmt)
    except asyncio.TimeoutError:
        logger.error("⏱ DB query timeout")
        raise
    except Exception as e:
        logger.error(f"DB execute error: {e}")
        raise


# ================= GRACEFUL SHUTDOWN =================
async def close_db():
    try:
        await engine.dispose()
        logger.info("🛑 DB engine closed")
    except Exception as e:
        logger.error(f"Error closing DB: {e}")