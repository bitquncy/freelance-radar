"""Add durable notification delivery outbox.

Revision ID: c82f1e8ad501
Revises: b7d8a42c9e10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c82f1e8ad501"
down_revision: Union[str, None] = "b7d8a42c9e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["project_analyses.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", name="uq_notification_analysis"),
    )
    op.create_index(
        "ix_notification_deliveries_analysis_id",
        "notification_deliveries",
        ["analysis_id"],
    )
    op.create_index(
        "ix_notification_deliveries_project_id",
        "notification_deliveries",
        ["project_id"],
    )
    op.create_index(
        "ix_notification_deliveries_user_id",
        "notification_deliveries",
        ["user_id"],
    )
    op.create_index(
        "ix_notification_due",
        "notification_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_due", table_name="notification_deliveries")
    op.drop_index(
        "ix_notification_deliveries_user_id",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_project_id",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_analysis_id",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
