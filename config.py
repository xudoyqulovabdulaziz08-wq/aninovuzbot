import os
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    VALKEY_URL = os.getenv("VALKEY_URL")
    DATABASE_URL = os.getenv("DATABASE_URL")

config = Config()