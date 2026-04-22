import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    VALKEY_URL: str = os.getenv("VALKEY_URL", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

config = Config()