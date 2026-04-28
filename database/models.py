from datetime import datetime, timezone
from typing import List, Optional
import uuid

from sqlalchemy import (
    CheckConstraint, Numeric, String, Integer, BigInteger, Boolean,
    Table, Text, DateTime, ForeignKey, Index, UniqueConstraint, Column
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from decimal import Decimal




# ================= BASE =================
class Base(DeclarativeBase):
    pass


# ================= ASSOCIATION TABLE =================
anime_genre = Table(
    "anime_genre",
    Base.metadata,
    Column("anime_id", ForeignKey("anime_list.anime_id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True)
)


# ================= USER =================
class DBUser(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    points: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="user", index=True)
    vip_expire_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    health_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    referral_count: Mapped[int] = mapped_column(Integer, default=0)
    referred_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    
    # Relationships
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    history: Mapped[List["History"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship(back_populates="user")
    tickets: Mapped[List["Ticket"]] = relationship(back_populates="user")
    admin_settings: Mapped[Optional["AdminSettings"]] = relationship(back_populates="user", uselist=False)
    @property
    def is_vip(self) -> bool:
        if self.status != "vip":
            return False
        # datetime.now(timezone.utc) ishlatish xavfsizroq
        if self.vip_expire_date:
            # expire_date timezone-aware bo'lishi kerak
            return self.vip_expire_date.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        return True
# ================= GENRE =================
class Genre(Base):
    __tablename__ = "genres"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


# ================= ANIME =================
class Anime(Base):
    __tablename__ = "anime_list"
    __table_args__ = (
        Index("idx_anime_title", "title"),
        Index("idx_anime_year", "year"),
    )

    anime_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    poster_id: Mapped[Optional[str]] = mapped_column(String(255))
    lang: Mapped[Optional[str]] = mapped_column(String(100))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    fandub: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    rating_sum: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    views_week: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    genres: Mapped[List["Genre"]] = relationship(secondary=anime_genre, backref="animes")
    episodes: Mapped[List["Episode"]] = relationship(back_populates="anime", cascade="all, delete-orphan")
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="anime", cascade="all, delete-orphan")
    history: Mapped[List["History"]] = relationship(back_populates="anime", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship(back_populates="anime", cascade="all, delete-orphan")

    @property
    def average_rating(self) -> float:
        if self.rating_count > 0:
            return round(float(self.rating_sum / self.rating_count), 1)
        return 0.0
# ================= EPISODE =================
class Episode(Base):
    __tablename__ = "anime_episodes"
    __table_args__ = (
        Index("idx_episode_anime", "anime_id"),
        UniqueConstraint("anime_id", "episode", name="uix_anime_episode"),
        CheckConstraint("episode > 0", name="check_episode_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime_list.anime_id", ondelete="CASCADE"))
    episode: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[str] = mapped_column(String(255))

    anime: Mapped["Anime"] = relationship(back_populates="episodes")


# ================= FAVORITE =================
class Favorite(Base):
    __tablename__ = "favorites"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime_list.anime_id", ondelete="CASCADE"), primary_key=True)

    # ✅ TUZATILDI: back_populates="favorites" (oldin "user" deb xato yozilgandi)
    user: Mapped["DBUser"] = relationship(back_populates="favorites")
    anime: Mapped["Anime"] = relationship(back_populates="favorites")



# ================= HISTORY =================
class History(Base):
    __tablename__ = "history"
    __table_args__ = (
        UniqueConstraint("user_id", "anime_id", name="uix_user_anime_history"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime_list.anime_id", ondelete="CASCADE"))
    last_episode: Mapped[int] = mapped_column(Integer, default=1)
    # onupdate qo'shildi!
    watched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["DBUser"] = relationship(back_populates="history")
    anime: Mapped["Anime"] = relationship(back_populates="history")

# ================= COMMENT =================
class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("idx_comment_anime", "anime_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("comments.id", ondelete="CASCADE"))
    parent: Mapped[Optional["Comment"]] = relationship(remote_side=[id], backref="replies")
    # Comment modelida shunday qilish xavfsizroq:
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime_list.anime_id", ondelete="CASCADE"))
    comment_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["DBUser"] = relationship(back_populates="comments")
    anime: Mapped["Anime"] = relationship(back_populates="comments")


# ================= TICKET =================
class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    message: Mapped[str] = mapped_column(Text)
    file_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["DBUser"] = relationship(back_populates="tickets")


# ================= BOSHQA JADVALLAR =================
class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HelpPage(Base):
    __tablename__ = "help_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)


class FanGroup(Base):
    __tablename__ = "fan_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    link: Mapped[str] = mapped_column(String(255), nullable=False)
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Advertisement(Base):
    __tablename__ = "advertisements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_type: Mapped[str] = mapped_column(String(20))
    target_group: Mapped[str] = mapped_column(String(20))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AdminSettings(Base):
    __tablename__ = "admin_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="moderator")
    user: Mapped["DBUser"] = relationship(back_populates="admin_settings")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    aggregate: Mapped[str] = mapped_column(String, nullable=False)   # Jadval nomi
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False) # PK qiymati
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))




MODELS_TO_WATCH = [Anime, DBUser, Episode, Channel, Favorite, History, Comment]