import os
import sys
from logging.config import fileConfig
from pathlib import Path
from dotenv import load_dotenv

from alembic import context
from sqlalchemy import engine_from_config, pool

# 1. .env faylini loyiha ildizidan majburiy yuklaymiz
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# 2. Alembic Config ob'ekti
config = context.config

# 3. alembic.ini ichidagi loglarni ishga tushirish
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 4. Modellaringizning Metadata qismini import qiling
# CHALKASHLIK BO'LMASLIGI UCHUN O'ZINGIZNING MODELINGIZGA QARAB TO'G'RILANG:
from database.models import Base  
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    This configures the context with just a URL and not an Engine.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ XATOLIK: DATABASE_URL .env faylidan topilmadi!")
        return

    print("--> Offline migratsiya boshlandi...")
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()
    print("--> Offline migratsiya yakunlandi.")


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    db_url = os.getenv("DATABASE_URL")
    wallet_location = os.getenv("DB_WALLET_LOCATION")

    # Nisbiy yo'lni absolyutga aylantirish (Kafolat)
    if wallet_location:
        wallet_path = Path(wallet_location)
        if not wallet_path.is_absolute():
            wallet_path = BASE_DIR / wallet_path
        wallet_location = str(wallet_path)
    else:
        wallet_location = str(BASE_DIR / "certs")

    configuration = config.get_section(config.config_ini_section, {})
    if db_url:
        configuration["sqlalchemy.url"] = db_url

    # Oracle ulanish argumentlari
    connect_args = {
        "config_dir": wallet_location,
        "wallet_location": wallet_location
    }

    print(f"--> Oracle config_dir ulanmoqda: {wallet_location}")

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    try:
        with connectable.connect() as connection:
            print("--> Baza bilan aloqa o'rnatildi. Migratsiya yuborilmoqda...")
            context.configure(
                connection=connection, 
                target_metadata=target_metadata
            )

            with context.begin_transaction():
                context.run_migrations()
            print("--> Jadvallar muvaffaqiyatli yangilandi!")
    except Exception as e:
        print(f"❌ ULANISHDA XATOLIK: {e}")
        raise e


# Qaysi rejimda ishlashni tanlash
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
