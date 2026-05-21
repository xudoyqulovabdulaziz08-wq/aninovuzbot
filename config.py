import os
import logging
from dataclasses import dataclass, field
from typing import List, Any, Optional
from dotenv import load_dotenv

# ================= ENV LOAD =================
if os.path.exists(".env"):
    load_dotenv()

logger = logging.getLogger("Config")


# ================= SAFE CAST =================
def safe_cast(key: str, default: Any, target_type: type = int):
    val = os.getenv(key)

    if val is None or val.strip() == "":
        return default

    try:
        return target_type(val)
    except Exception:
        logger.warning(f"⚠️ Invalid env {key}='{val}', using default={default}")
        return default


# ================= CONFIG =================
@dataclass(frozen=True)
class Config:

    # ================= BOT CORE =================
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    CREATOR_ID: int = safe_cast("CREATOR_ID", 0)

    # ================= INFRA =================
    VALKEY_URL: str = os.getenv(
        "VALKEY_URL",
        os.getenv("VALKEY_UR", "")
    )

    VALKEY_SSL_SKIP: bool = os.getenv("VALKEY_SSL_SKIP", "true").lower() == "true"

    # ================= DATABASE =================
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    DB_POOL_SIZE: int = safe_cast("DB_POOL_SIZE", 10)
    DB_MAX_OVERFLOW: int = safe_cast("DB_MAX_OVERFLOW", 20)

    # ================= SERVER =================
    PORT: int = safe_cast("PORT", 8000)
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "").strip()
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # ================= ADMIN =================
    ADMIN_IDS: List[int] = field(default_factory=list)

    # ================= WEBHOOK =================
    @property
    def WEBHOOK_PATH(self) -> str:
        return f"/webhook/{self.BOT_TOKEN}"

    @property
    def WEBHOOK_URL(self) -> str:
        if not self.WEBHOOK_HOST:
            return ""
        return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"

    # ================= INIT VALIDATION =================
    def __post_init__(self):

        errors = []

        # ---- critical checks ----
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN missing")

        if not self.DATABASE_URL:
            errors.append("DATABASE_URL missing")

        # ---- production strict mode ----
        if not self.DEBUG and not self.WEBHOOK_HOST:
            errors.append("WEBHOOK_HOST required in production")

        if errors:
            msg = "❌ CONFIG FAILURE:\n - " + "\n - ".join(errors)
            logger.critical(msg)
            raise RuntimeError(msg)

        # ================= ADMIN PARSING =================
        raw = os.getenv("ADMIN_IDS", "")

        parsed = []
        if raw:
            try:
                parsed = [
                    int(x.strip())
                    for x in raw.split(",")
                    if x.strip().isdigit()
                ]
            except Exception as e:
                logger.error(f"ADMIN_IDS parse error: {e}")

        object.__setattr__(self, "ADMIN_IDS", parsed)

        # ================= FINAL LOG =================
        logger.info(
            "✅ Config loaded | "
            f"PORT={self.PORT} | "
            f"DEBUG={self.DEBUG} | "
            f"ADMINS={len(self.ADMIN_IDS)}"
        )


# ================= SINGLETON =================
config = Config()