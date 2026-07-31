"""subscription expiry reminders

Adds ``users.expiry_notified_at`` so the expiry-reminder job is idempotent:
one nudge per subscription period, never a daily nag (§3.8 spirit).

Revision ID: a1c7e93f5b20
Revises: d4f51504d763
Create Date: 2026-07-30 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c7e93f5b20'
down_revision: Union[str, None] = 'd4f51504d763'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('expiry_notified_at', sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('expiry_notified_at')
