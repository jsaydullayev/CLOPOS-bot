"""greeting photo: bot_texts.photo_*, value may be empty

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode, so the same migration also runs on SQLite (tests).
    with op.batch_alter_table("bot_texts") as table:
        table.alter_column("value", existing_type=sa.Text(), nullable=True)
        table.add_column(sa.Column("photo_file_id", sa.Text(), nullable=True))
        table.add_column(sa.Column("photo_unique_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM bot_texts WHERE value IS NULL")
    with op.batch_alter_table("bot_texts") as table:
        table.drop_column("photo_unique_id")
        table.drop_column("photo_file_id")
        table.alter_column("value", existing_type=sa.Text(), nullable=False)
