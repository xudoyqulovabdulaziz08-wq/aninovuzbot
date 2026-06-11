"""oracle_final_tables

Revision ID: 684961695b08
Revises: 
Create Date: 2026-06-10 23:50:29.606556

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '684961695b08'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema - FAQAT OCHILMAY QOLGAN JADVALLAR UCHUN"""
    
    # 1. OUTBOX_EVENTS jadvalini yaratish (Oracle UUID va JSON cheklovlari to'g'rilangan)
    op.create_table('outbox_events',
    # UUID o'rniga String(36) qo'llaymiz:
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('aggregate', sa.String(length=255), nullable=False),
    sa.Column('aggregate_id', sa.String(length=255), nullable=False),
    sa.Column('event_type', sa.String(length=255), nullable=False),
    sa.Column('payload', sa.Text(), server_default='{}', nullable=False),
    sa.Column('event_hash', sa.String(length=64), nullable=True),
    sa.Column('processed', sa.Boolean(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbox_events_aggregate'), 'outbox_events', ['aggregate'], unique=False)
    op.create_index(op.f('ix_outbox_events_aggregate_id'), 'outbox_events', ['aggregate_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_created_at'), 'outbox_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_outbox_events_event_hash'), 'outbox_events', ['event_hash'], unique=False)
    op.create_index(op.f('ix_outbox_events_event_type'), 'outbox_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_outbox_events_priority'), 'outbox_events', ['priority'], unique=False)
    op.create_index(op.f('ix_outbox_events_processed'), 'outbox_events', ['processed'], unique=False)
    op.create_index(op.f('ix_outbox_events_processed_at'), 'outbox_events', ['processed_at'], unique=False)

    # 2. USERS jadvalini yaratish
    op.create_table('users',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=255), nullable=True),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('user', 'vip', 'admin', name='user_status', inherit_schema=True), nullable=False),
    sa.Column('vip_expire_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('health_mode', sa.Boolean(), nullable=False),
    sa.Column('referral_count', sa.Integer(), nullable=False),
    sa.Column('last_redirected_channel', sa.String(length=50), nullable=True),
    sa.Column('referred_by_channel', sa.String(length=50), nullable=True),
    sa.Column('referred_by', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['referred_by'], ['users.user_id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index('idx_user_points_fast', 'users', ['status', 'points'], unique=False)
    op.create_index('idx_user_ref_fast', 'users', ['referral_count'], unique=False)
    op.create_index(op.f('ix_users_joined_at'), 'users', ['joined_at'], unique=False)
    op.create_index(op.f('ix_users_points'), 'users', ['points'], unique=False)
    op.create_index(op.f('ix_users_referred_by'), 'users', ['referred_by'], unique=False)
    op.create_index(op.f('ix_users_status'), 'users', ['status'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)

    # 3. ADMIN_SETTINGS jadvalini yaratish
    op.create_table('admin_settings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('role', sa.Enum('owner', 'admin', 'moderator', name='admin_role', inherit_schema=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_admin_role', 'admin_settings', ['role'], unique=False)
    op.create_index(op.f('ix_admin_settings_user_id'), 'admin_settings', ['user_id'], unique=True)

    # 4. ANIME_EPISODES jadvalini yaratish
    op.create_table('anime_episodes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('episode', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['anime_id'], ['anime_list.anime_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('anime_id', 'episode')
    )
    op.create_index(op.f('ix_anime_episodes_anime_id'), 'anime_episodes', ['anime_id'], unique=False)
    op.create_index(op.f('ix_anime_episodes_file_id'), 'anime_episodes', ['file_id'], unique=False)

    # 5. ANIME_GENRES jadvalini yaratish
    op.create_table('anime_genres',
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('genre_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['anime_id'], ['anime_list.anime_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['genre_id'], ['genres.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('anime_id', 'genre_id')
    )
    op.create_index('idx_anime_id', 'anime_genres', ['anime_id'], unique=False)
    op.create_index('idx_genre_id', 'anime_genres', ['genre_id'], unique=False)

    # 6. COMMENTS jadvalini yaratish
    op.create_table('comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('comment_text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['anime_id'], ['anime_list.anime_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['comments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_comment_anime', 'comments', ['anime_id'], unique=False)
    op.create_index('idx_comment_parent', 'comments', ['parent_id'], unique=False)
    op.create_index('idx_comment_user', 'comments', ['user_id'], unique=False)
    op.create_index(op.f('ix_comments_created_at'), 'comments', ['created_at'], unique=False)

    # 7. FAVORITES jadvalini yaratish
    op.create_table('favorites',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['anime_id'], ['anime_list.anime_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'anime_id')
    )
    op.create_index('idx_fav_anime', 'favorites', ['anime_id'], unique=False)

    # 8. HISTORY jadvalini yaratish
    op.create_table('history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('watched_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['anime_id'], ['anime_list.anime_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_history_anime', 'history', ['anime_id'], unique=False)
    op.create_index('idx_history_user', 'history', ['user_id'], unique=False)
    op.create_index(op.f('ix_history_watched_at'), 'history', ['watched_at'], unique=False)

    # 9. TICKETS jadvalini yaratish
    op.create_table('tickets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('file_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.Enum('open', 'closed', 'pending', name='ticket_status', inherit_schema=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ticket_created', 'tickets', ['created_at'], unique=False)
    op.create_index('idx_ticket_status', 'tickets', ['status'], unique=False)
    op.create_index('idx_ticket_user', 'tickets', ['user_id'], unique=False)
    op.create_index(op.f('ix_tickets_file_id'), 'tickets', ['file_id'], unique=False)

    # Qo'shimcha indekslar
    op.create_index(op.f('ix_advertisements_created_at'), 'advertisements', ['created_at'], unique=False)
    op.create_index(op.f('ix_advertisements_end_date'), 'advertisements', ['end_date'], unique=False)
    op.create_index(op.f('ix_anime_list_views_week'), 'anime_list', ['views_week'], unique=False)

def downgrade() -> None:
    pass