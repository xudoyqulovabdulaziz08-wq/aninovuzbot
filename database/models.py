from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import JSON
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import (
    String, Integer, BigInteger, Boolean,
    Text, DateTime, ForeignKey, Index,
    UniqueConstraint, Column, Table, Numeric, Enum
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
anime_genres = Table(
    "anime_genres",
    Base.metadata,
    Column("anime_id", ForeignKey("anime_list.anime_id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_anime_id", "anime_id"),
    Index("idx_genre_id", "genre_id"),
)
# ================= USER =================
class DBUser(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    username: Mapped[Optional[str]] = mapped_column(
        String(255),
        index=True
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    points: Mapped[int] = mapped_column(Integer, default=0, index=True)

    status: Mapped[str] = mapped_column(
        Enum("user", "vip", "admin", name="user_status"),
        default="user",
        index=True
    )

    vip_expire_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    health_mode: Mapped[bool] = mapped_column(Boolean, default=True)

    referral_count: Mapped[int] = mapped_column(Integer, default=0, index=True)

    last_redirected_channel: Mapped[Optional[str]] = mapped_column(String(50))
    referred_by_channel: Mapped[Optional[str]] = mapped_column(String(50))

    # 🔴 FK QO‘SHILDI (ENG MUHIM FIX)
    referred_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        index=True
    )

    # 🔥 SELF RELATION
    referred_by_user: Mapped[Optional["DBUser"]] = relationship(
        "DBUser",
        remote_side=[user_id],
        backref="referrals",
        lazy="joined"
    )

    # ================= RELATIONSHIPS =================

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
        Index("idx_user_points_fast", "status", "points"),
        Index("idx_user_ref_fast", "referral_count"),
    )

    # 🔥 HYBRID (queryda ham ishlaydi)
    @hybrid_property
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

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True
    )

    # optional
    animes: Mapped[List["Anime"]] = relationship(
        "Anime",
        secondary="anime_genres",
        back_populates="genres",
        lazy="selectin"
    )



# ================= ANIME =================
class Anime(Base):
    __tablename__ = "anime_list"

    anime_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True
    )

    poster_id: Mapped[Optional[str]] = mapped_column(String(255))

    year: Mapped[Optional[int]] = mapped_column(Integer, index=True)

    rating_sum: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    views_week: Mapped[int] = mapped_column(Integer, default=0, index=True)

    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    genres: Mapped[List["Genre"]] = relationship(
        secondary=anime_genres,
        back_populates="animes",
        lazy="selectin"
    )

    episodes: Mapped[List["Episode"]] = relationship(
        "Episode",
        back_populates="anime",
        cascade="all, delete-orphan",
        order_by="Episode.episode",
        lazy="selectin"
    )

    favorites: Mapped[List["Favorite"]] = relationship(
        back_populates="anime",
        lazy="selectin"
    )

    history: Mapped[List["History"]] = relationship(
        back_populates="anime",
        lazy="selectin"
    )

    __table_args__ = (
        Index("idx_anime_search", "title"),
        Index("idx_anime_year", "year"),
    )

    @hybrid_property
    def average_rating(self):
        if self.rating_count:
            return self.rating_sum / self.rating_count
        return 0
    


# ================= EPISODE =================
class Episode(Base):
    __tablename__ = "anime_episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime_list.anime_id", ondelete="CASCADE"),
        index=True
    )

    episode: Mapped[int] = mapped_column(Integer)

    file_id: Mapped[str] = mapped_column(String(255), index=True)

    anime: Mapped["Anime"] = relationship(
        back_populates="episodes"
    )

    __table_args__ = (
        UniqueConstraint("anime_id", "episode"),
    )
# ================= FAVORITE =================
class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True
    )

    anime_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("anime_list.anime_id", ondelete="CASCADE"),
        primary_key=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    user: Mapped["DBUser"] = relationship(
        back_populates="favorites",
        lazy="selectin"
    )

    anime: Mapped["Anime"] = relationship(
        back_populates="favorites",
        lazy="selectin"
    )

    __table_args__ = (
        Index("idx_fav_anime", "anime_id"),
    )



# ================= HISTORY =================
class History(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        index=True
    )

    anime_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("anime_list.anime_id", ondelete="CASCADE"),
        index=True
    )

    watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    user: Mapped["DBUser"] = relationship(
        "DBUser",
        back_populates="history",
        lazy="selectin"
    )

    anime: Mapped["Anime"] = relationship(
        "Anime",
        back_populates="history",
        lazy="selectin"
    )

    __table_args__ = (
        Index("idx_history_user", "user_id"),
        Index("idx_history_anime", "anime_id"),
    )
# ================= COMMENT =================
class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    anime_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("anime_list.anime_id", ondelete="CASCADE"),
        index=True
    )

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

    user: Mapped[Optional["DBUser"]] = relationship(
        "DBUser",
        back_populates="comments",
        lazy="selectin"
    )

    replies: Mapped[List["Comment"]] = relationship(
        "Comment",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    parent: Mapped[Optional["Comment"]] = relationship(
        "Comment",
        back_populates="replies",
        remote_side=[id]
    )

    __table_args__ = (
        Index("idx_comment_anime", "anime_id"),
        Index("idx_comment_user", "user_id"),
        Index("idx_comment_parent", "parent_id"),
    )



# ================= TICKET =================
class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        index=True
    )

    message: Mapped[str] = mapped_column(Text)

    file_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)

    status: Mapped[str] = mapped_column(
        Enum("open", "closed", "pending", name="ticket_status"),
        default="open",
        index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    user: Mapped[Optional["DBUser"]] = relationship(
        "DBUser",
        back_populates="tickets",
        lazy="selectin"
    )

    __table_args__ = (
        Index("idx_ticket_user", "user_id"),
        Index("idx_ticket_status", "status"),
        Index("idx_ticket_created", "created_at"),
    )
# ================= BOSHQA JADVALLAR =================
class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )

    channel_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    url: Mapped[Optional[str]] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    __table_args__ = (
        Index("idx_channel_active", "is_active"),
    )



#=============HelpPage===================    
class HelpPage(Base):
    __tablename__ = "help_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    page_number: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        index=True,
        nullable=False
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )


#=============FanGroup=====================
class FanGroup(Base):
    __tablename__ = "fan_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False
    )

    link: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        Index("idx_fan_active", "is_active"),
        Index("idx_fan_vip", "is_vip"),
    )






#==========================================================
class Advertisement(Base):
    __tablename__ = "advertisements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ad_type: Mapped[str] = mapped_column(
        Enum("banner", "post", "video", name="ad_type"),
        nullable=False,
        index=True
    )

    target_group: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False
    )

    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    end_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    __table_args__ = (
        Index("idx_ad_active", "is_active"),
        Index("idx_ad_type", "ad_type"),
        Index("idx_ad_target", "target_group"),
    )



#==========================================================
class AdminSettings(Base):
    __tablename__ = "admin_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        unique=True,
        index=True
    )

    role: Mapped[str] = mapped_column(
        Enum("owner", "admin", "moderator", name="admin_role"),
        default="moderator",
        index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    user: Mapped["DBUser"] = relationship(
        "DBUser",
        back_populates="admin_settings",
        uselist=False
    )

    __table_args__ = (
        Index("idx_admin_role", "role"),
    )




#==========================================================



class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4
    )

    aggregate: Mapped[str] = mapped_column(String, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, index=True)

    event_type: Mapped[str] = mapped_column(String, index=True)

    payload: Mapped[dict] = mapped_column(JSON)

    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True
    )



# ================= OUTBOX CONFIG =================

# Keshni yangilashi yoki hodisalarni kuzatishi kerak bo'lgan modellar ro'yxati[cite: 16]
MODELS_TO_WATCH = [
    DBUser,
    Anime,
    Episode,
    Genre,
    Favorite,
    Comment,
    Ticket,
    Channel,
    FanGroup,
    Advertisement,
    AdminSettings
]