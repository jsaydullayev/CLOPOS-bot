"""section emoji: categories.emoji

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("emoji", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "emoji")
