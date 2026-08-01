"""Move broadcast groups and durable queue into the shared SQL database.

Revision ID: e41b6a902fd2
Revises: c82f1e8ad501
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e41b6a902fd2"
down_revision: Union[str, None] = "c82f1e8ad501"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broadcast_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_telegram_id", "name", name="uq_broadcast_group_owner_name"
        ),
    )
    op.create_index(
        "ix_broadcast_groups_owner_telegram_id",
        "broadcast_groups",
        ["owner_telegram_id"],
    )
    op.create_table(
        "broadcast_recipients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deactivated_reason", sa.String(length=255), nullable=True),
        sa.Column("last_broadcast_at", sa.DateTime(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["broadcast_groups.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id", "chat_id", name="uq_broadcast_recipient_group_chat"
        ),
    )
    op.create_index(
        "ix_broadcast_recipient_audience",
        "broadcast_recipients",
        ["group_id", "is_active", "chat_type"],
    )
    op.create_index(
        "ix_broadcast_recipients_group_id", "broadcast_recipients", ["group_id"]
    )
    op.create_table(
        "broadcast_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("reply_markup", sa.JSON(), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("disable_notification", sa.Boolean(), nullable=False),
        sa.Column("protect_content", sa.Boolean(), nullable=False),
        sa.Column("progress_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("progress_message_id", sa.Integer(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["broadcast_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_broadcast_campaign_due", "broadcast_campaigns", ["status", "scheduled_at"]
    )
    op.create_index(
        "ix_broadcast_campaigns_group_id", "broadcast_campaigns", ["group_id"]
    )
    op.create_index(
        "ix_broadcast_campaigns_owner_telegram_id",
        "broadcast_campaigns",
        ["owner_telegram_id"],
    )
    op.create_table(
        "broadcast_targets_v2",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("broadcast_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["broadcast_id"], ["broadcast_campaigns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "chat_id", name="uq_broadcast_target_chat"),
    )
    op.create_index(
        "ix_broadcast_target_claim",
        "broadcast_targets_v2",
        ["broadcast_id", "status", "id"],
    )
    op.create_index(
        "ix_broadcast_targets_v2_broadcast_id",
        "broadcast_targets_v2",
        ["broadcast_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_broadcast_targets_v2_broadcast_id", table_name="broadcast_targets_v2"
    )
    op.drop_index("ix_broadcast_target_claim", table_name="broadcast_targets_v2")
    op.drop_table("broadcast_targets_v2")
    op.drop_index(
        "ix_broadcast_campaigns_owner_telegram_id", table_name="broadcast_campaigns"
    )
    op.drop_index("ix_broadcast_campaigns_group_id", table_name="broadcast_campaigns")
    op.drop_index("ix_broadcast_campaign_due", table_name="broadcast_campaigns")
    op.drop_table("broadcast_campaigns")
    op.drop_index("ix_broadcast_recipients_group_id", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipient_audience", table_name="broadcast_recipients")
    op.drop_table("broadcast_recipients")
    op.drop_index(
        "ix_broadcast_groups_owner_telegram_id", table_name="broadcast_groups"
    )
    op.drop_table("broadcast_groups")
