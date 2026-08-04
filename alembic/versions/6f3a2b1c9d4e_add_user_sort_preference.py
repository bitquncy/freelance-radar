"""add per-user order-card sort preference (task_0004)

Revision ID: 6f3a2b1c9d4e
Revises: e41b6a902fd2
Create Date: 2026-07-26 12:00:00.000000

Users get a non-native VARCHAR enum column (follows the existing
``_enum_col`` convention in core/models.py). A NOT NULL ``server_default``
backfills existing rows on the way up; the model-level Python default still
applies for new rows.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "6f3a2b1c9d4e"
down_revision: Union[str, None] = "e41b6a902fd2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "sort_preference",
                sa.String(length=32),
                server_default="default",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("sort_preference")
