import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN: str    = os.getenv("BOT_TOKEN", "")
    VALKEY_URL: str   = os.getenv("VALKEY_URL", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Webhook uchun (Render avtomatik PORT beradi)
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")   # https://sizning-bot.onrender.com
    PORT: int         = int(os.getenv("PORT", "27624"))

config = Config()