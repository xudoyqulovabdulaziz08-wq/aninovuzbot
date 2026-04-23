"""fix_user_table2

Revision ID: 1478c06f906e
Revises: 4d95d4b26680
Create Date: 2026-04-23 18:26:08.463719

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1478c06f906e'
down_revision: Union[str, Sequence[str], None] = '4d95d4b26680'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
