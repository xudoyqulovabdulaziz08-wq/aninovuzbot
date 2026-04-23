import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# Productionda (Render/Docker) odatda ENV'lar tayyor bo'ladi, 
# lekin local development uchun load_dotenv'ni shartli ravishda qoldiramiz.
if os.path.exists(".env"):
    load_dotenv()

@dataclass(frozen=True)
class Config:
    # --- BOT CORE ---
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CREATOR_ID: int = int(os.getenv("CREATOR_ID", "0"))
    
    # --- INFRASTRUCTURE ---
    VALKEY_URL: str = os.getenv("VALKEY_URL", "redis://localhost:6379/0")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # --- SERVER SETTINGS ---
    PORT: int = int(os.getenv("PORT", "8000"))
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    # --- ADMINS ---
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x and x.strip().isdigit()
    ])

    # --- 10/10 FIX: DYNAMIC PROPERTIES ---
    # Bu metodlar BOT_TOKEN va HOST tayyor bo'lgandagina chaqiriladi
    @property
    def WEBHOOK_PATH(self) -> str:
        return f"/webhook/{self.BOT_TOKEN}"

    @property
    def WEBHOOK_URL(self) -> str:
        if not self.WEBHOOK_HOST:
            return ""
        return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"

    def __post_init__(self):
        """Olmos darajasidagi validation: Failing Fast strategy."""
        errors = []
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN")
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL")
        
        if errors:
            critical_msg = f"❌ CRITICAL CONFIG ERROR: Missing keys: {', '.join(errors)}"
            logging.critical(critical_msg)
            raise ValueError(critical_msg)

# Singleton instance
config = Config()