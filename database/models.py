from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    String, Integer, BigInteger, Boolean,
    Text, DateTime, ForeignKey, Index,
    UniqueConstraint, Column, Table, Numeric
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column,
    relationship
)
from sqlalchemy.sql import func

# ================= BASE =================
class Base(DeclarativeBase):
    """Shared base for all models"""
    pass
# ================= ASSOCIATION TABLE =================
anime_genre = Table(
    "anime_genre",
    Base.metadata,
    Column("anime_id", ForeignKey("anime_list.anime_id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_anime_genre_fast", "anime_id", "genre_id")
)

# ================= USER =================
class DBUser(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    points: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(20), default="user", index=True)

    vip_expire_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    health_mode: Mapped[bool] = mapped_column(Boolean, default=True)

    referral_count: Mapped[int] = mapped_column(Integer, default=0, index=True)

    last_redirected_channel: Mapped[Optional[str]] = mapped_column(String(50))

    referred_by_channel: Mapped[Optional[str]] = mapped_column(String(50))

    referred_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL")
    )

    # 🔥 PERFORMANCE: lazy='selectin' = N+1 fix
    favorites: Mapped[List["Favorite"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    history: Mapped[List["History"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    comments: Mapped[List["Comment"]] = relationship(
        "Comment",
        back_populates="user",
        primaryjoin="DBUser.user_id == Comment.user_id", 
        lazy="selectin"
    )

    tickets: Mapped[List["Ticket"]] = relationship(
        back_populates="user",
        lazy="selectin"
    )

    admin_settings: Mapped[Optional["AdminSettings"]] = relationship(
        back_populates="user",
        uselist=False,
        lazy="joined"
    )

    __table_args__ = (
        Index("idx_user_points_fast", "points", "status"),
        Index("idx_user_ref_fast", "referral_count"),
    )

    @property
    def is_vip(self) -> bool:
        if self.status != "vip":
            return False
        if not self.vip_expire_date:
            return True
        return self.vip_expire_date > datetime.now(timezone.utc)
# ================= GENRE =================
class Genre(Base):
    __tablename__ = "genres"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


# ================= ANIME =================
class Anime(Base):
    __tablename__ = "anime_list"

    anime_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    poster_id: Mapped[Optional[str]] = mapped_column(String(255))

    year: Mapped[Optional[int]] = mapped_column(Integer, index=True)

    rating_sum: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    views_week: Mapped[int] = mapped_column(Integer, default=0, index=True)

    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    genres: Mapped[List["Genre"]] = relationship(
        secondary=anime_genre,
        backref="animes",
        lazy="selectin"
    )

    episodes: Mapped[List["Episode"]] = relationship(
        back_populates="anime",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    favorites: Mapped[List["Favorite"]] = relationship(lazy="selectin")
    history: Mapped[List["History"]] = relationship(lazy="selectin")

    __table_args__ = (
        Index("idx_anime_fast_search", "title", "year"),
    )

    @property
    def average_rating(self) -> float:
        if self.rating_count:
            return round(float(self.rating_sum / self.rating_count), 1)
        return 0.0
# ================= EPISODE =================
class Episode(Base):
    __tablename__ = "anime_episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime_list.anime_id", ondelete="CASCADE"),
        index=True
    )

    episode: Mapped[int] = mapped_column(Integer, index=True)

    file_id: Mapped[str] = mapped_column(String(255))

    anime: Mapped["Anime"] = relationship(back_populates="episodes")

    __table_args__ = (
        UniqueConstraint("anime_id", "episode"),
        Index("idx_episode_fast", "anime_id", "episode"),
    )
# ================= FAVORITE =================
class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    anime_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("anime_list.anime_id", ondelete="CASCADE"), primary_key=True)

    user: Mapped["DBUser"] = relationship(back_populates="favorites", lazy="joined")
    anime: Mapped["Anime"] = relationship(back_populates="favorites", lazy="joined")



# ================= HISTORY =================
class History(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 🟢 TO'G'IRLANDI: ForeignKey qo'shildi
    user_id: Mapped[int] = mapped_column(
        BigInteger, 
        ForeignKey("users.user_id", ondelete="CASCADE"), 
        index=True
    )
    # 🟢 TO'G'IRLANDI: Anime uchun ham bog'liqlik qo'shish tavsiya etiladi
    anime_id: Mapped[int] = mapped_column(
        BigInteger, 
        ForeignKey("anime_list", ondelete="CASCADE"), 
        index=True
    )

    watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    # 🟢 QO'SHILDI: relationship orqaga qaytishi uchun (back_populates uchun shart)
    user: Mapped["DBUser"] = relationship(back_populates="history")

# ================= COMMENT =================
class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 🟢 TO'G'IRLANDI: anime_list.id EMAS, anime_list.anime_id bo'lishi kerak
    anime_id: Mapped[int] = mapped_column(
        BigInteger, 
        ForeignKey("anime_list.anime_id", ondelete="CASCADE"), 
        index=True
    )

    # 🟢 TO'G'IRLANDI: Foydalanuvchiga bog'liqlik (ForeignKey)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, 
        ForeignKey("users.user_id", ondelete="SET NULL"), 
        index=True
    )

    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("comments.id", ondelete="CASCADE")
    )

    comment_text: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    # 🟢 TO'G'IRLANDI: DBUser bilan munosabat
    user: Mapped[Optional["DBUser"]] = relationship(
        "DBUser",
        back_populates="comments",
        primaryjoin="Comment.user_id == DBUser.user_id" # <--- Shuni qo'shing
    )
    
    # 🟢 TO'G'IRLANDI: Replies uchun back_populates (self-referential)
    replies: Mapped[List["Comment"]] = relationship(
        "Comment", 
        back_populates="parent",
        lazy="selectin"
    )
    parent: Mapped[Optional["Comment"]] = relationship(
        "Comment", 
        back_populates="replies", 
        remote_side=[id]
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    user: Mapped["DBUser"] = relationship(back_populates="tickets")


# ================= BOSHQA JADVALLAR =================
class Channel(Base):
    __tablename__ = "channels"

    # 1. Primary keyni ham BigInteger qilish tavsiya etiladi
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 2. Telegram ID uchun BigInteger (Bu qism sizda zo'r turibdi)
    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
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

    aggregate: Mapped[str] = mapped_column(String, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, index=True)

    event_type: Mapped[str] = mapped_column(String, index=True)

    payload: Mapped[str] = mapped_column(Text)

    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

MODELS_TO_WATCH = [Anime, DBUser, Episode, Channel, Favorite, History, Comment]