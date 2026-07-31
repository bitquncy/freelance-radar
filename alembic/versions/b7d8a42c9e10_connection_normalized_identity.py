"""normalized Telegram source identity

Revision ID: b7d8a42c9e10
Revises: a1c7e93f5b20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d8a42c9e10"
down_revision: Union[str, None] = "a1c7e93f5b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("exchange_connections") as batch_op:
        batch_op.add_column(sa.Column("normalized_identity", sa.String(255), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, user_id, settings FROM exchange_connections WHERE platform = 'tg_channel' ORDER BY id")
    ).mappings()
    seen: set[tuple[int, str]] = set()
    for row in rows:
        settings = row["settings"] or {}
        channel = settings.get("channel", "") if isinstance(settings, dict) else ""
        normalized = str(channel).strip().casefold() or f"legacy:{row['id']}"
        key = (row["user_id"], normalized)
        if key in seen:
            # Preserve data safely: mark legacy duplicates inactive and assign a
            # unique migration identity instead of deleting user configuration.
            connection.execute(
                sa.text("UPDATE exchange_connections SET status='paused' WHERE id=:id"),
                {"id": row["id"]},
            )
            normalized = f"{normalized}#legacy-{row['id']}"
        seen.add(key)
        connection.execute(
            sa.text("UPDATE exchange_connections SET normalized_identity=:value WHERE id=:id"),
            {"id": row["id"], "value": normalized},
        )

    with op.batch_alter_table("exchange_connections") as batch_op:
        batch_op.create_unique_constraint(
            "uq_connections_user_platform_identity",
            ["user_id", "platform", "normalized_identity"],
        )


def downgrade() -> None:
    with op.batch_alter_table("exchange_connections") as batch_op:
        batch_op.drop_constraint("uq_connections_user_platform_identity", type_="unique")
        batch_op.drop_column("normalized_identity")
