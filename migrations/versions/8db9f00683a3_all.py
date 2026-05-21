"""all

Revision ID: 8db9f00683a3
Revises: 5ad713efa481
Create Date: 2026-05-21 18:09:00.000652

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8db9f00683a3'
down_revision: Union[str, Sequence[str], None] = '5ad713efa481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
