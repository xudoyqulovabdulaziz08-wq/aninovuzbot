import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Any
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv()

def safe_cast(key: str, default: Any, target_type: type = int):
    """Silent failure'ning oldini oluvchi xavfsiz casting."""
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    try:
        return target_type(val)
    except (ValueError, TypeError):
        logging.warning(f"⚠️ Config: Invalid value for {key}='{val}', using default: {default}")
        return default

@dataclass(frozen=True)
class Config:
    # --- BOT CORE (Strict Validation) ---
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    CREATOR_ID: int = safe_cast("CREATOR_ID", 0)
    
    # --- INFRASTRUCTURE ---
    VALKEY_URL: str = os.getenv("VALKEY_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379/0"
    # 🔥 10/10 FIX: Redis/Valkey TLS SSL Context (Render/Railway fix)
    VALKEY_SSL_SKIP: bool = os.getenv("VALKEY_SSL_SKIP", "True").lower() == "true"

    # --- DATABASE & POOLING ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    DB_POOL_SIZE: int = safe_cast("DB_POOL_SIZE", 5)
    DB_MAX_OVERFLOW: int = safe_cast("DB_MAX_OVERFLOW", 10)
    
    # --- SERVER SETTINGS ---
    PORT: int = safe_cast("PORT", 8000)
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "").strip()
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    # --- ADMINS (No Silent Failure) ---
    ADMIN_IDS: List[int] = field(default_factory=lambda: [])

    @property
    def WEBHOOK_PATH(self) -> str:
        return f"/webhook/{self.BOT_TOKEN}"

    @property
    def WEBHOOK_URL(self) -> str:
        # ✅ FIX: Webhook_host bo'sh bo'lsa, xato berishi kerak
        if not self.WEBHOOK_HOST:
            return ""
        return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"

    def __post_init__(self):
        """Industrial Level Integrity Check."""
        # 1. Critical Keys (Fail-Fast)
        critical_errors = []
        if not self.BOT_TOKEN: critical_errors.append("BOT_TOKEN")
        if not self.DATABASE_URL: critical_errors.append("DATABASE_URL")
        
        # 2. Webhook Check (Silent Failure Protection)
        if not self.DEBUG and not self.WEBHOOK_HOST:
            # Productionda webhook_host shart
            critical_errors.append("WEBHOOK_HOST (Required for Production)")

        if critical_errors:
            msg = f"❌ CRITICAL CONFIG FAILURE: Missing keys: {', '.join(critical_errors)}"
            logging.error(msg)
            raise ValueError(msg)

        # 3. ADMIN_IDS Manual Parsing (Safe context)
        raw_admins = os.getenv("ADMIN_IDS", "")
        if raw_admins:
            try:
                # Ghost Admin Bug Fix: FAQAT to'g'ri raqamlarni olamiz
                parsed_admins = [int(x.strip()) for x in raw_admins.split(",") if x.strip().isdigit()]
                # Dataclass frozen bo'lgani uchun object.__setattr__ ishlatamiz
                object.__setattr__(self, 'ADMIN_IDS', parsed_admins)
            except Exception as e:
                logging.error(f"❌ Failed to parse ADMIN_IDS: {e}")

# Singleton
config = Config()