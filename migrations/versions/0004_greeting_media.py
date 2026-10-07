"""greeting video: bot_texts.photo_* become media_*, with media_type

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bot_texts") as table:
        table.alter_column("photo_file_id", new_column_name="media_file_id", existing_type=sa.Text())
        table.alter_column("photo_unique_id", new_column_name="media_unique_id", existing_type=sa.String(length=64))
        table.add_column(sa.Column("media_type", sa.String(length=16), nullable=True))
    # Everything set before this revision is a photo.
    op.execute("UPDATE bot_texts SET media_type = 'photo' WHERE media_file_id IS NOT NULL")


def downgrade() -> None:
    # Only photos existed before: a video greeting is dropped, and a row left with nothing goes too.
    op.execute("UPDATE bot_texts SET media_file_id = NULL, media_unique_id = NULL WHERE media_type <> 'photo'")
    op.execute("DELETE FROM bot_texts WHERE value IS NULL AND media_file_id IS NULL")
    with op.batch_alter_table("bot_texts") as table:
        table.drop_column("media_type")
        table.alter_column("media_unique_id", new_column_name="photo_unique_id", existing_type=sa.String(length=64))
        table.alter_column("media_file_id", new_column_name="photo_file_id", existing_type=sa.Text())
