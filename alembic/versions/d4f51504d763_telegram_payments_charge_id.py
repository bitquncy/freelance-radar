"""telegram payments charge id

Revision ID: d4f51504d763
Revises: 22f35bdc2221
Create Date: 2026-07-25 19:30:15.294566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f51504d763'
down_revision: Union[str, None] = '22f35bdc2221'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('payment_charge_id', sa.String(length=255), nullable=True)
        )
        batch_op.create_unique_constraint(
            'uq_subscriptions_charge', ['payment_charge_id']
        )


def downgrade() -> None:
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_constraint('uq_subscriptions_charge', type_='unique')
        batch_op.drop_column('payment_charge_id')
