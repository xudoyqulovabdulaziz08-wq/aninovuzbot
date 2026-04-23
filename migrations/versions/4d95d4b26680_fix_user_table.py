"""fix_user_table

Revision ID: 4d95d4b26680
Revises: 2dbfa094cd39
Create Date: 2026-04-23 18:20:59.043037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d95d4b26680'
down_revision: Union[str, Sequence[str], None] = '2dbfa094cd39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
