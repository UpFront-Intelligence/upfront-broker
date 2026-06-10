"""properties: link recorded owner / manager / tax bill accounts

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-06-10

properties.owner_id remains the broker (data isolation) — untouched.
These three new FKs point at accounts (the LLC / party records) and are
nullable, ON DELETE SET NULL so a deleted account doesn't take the
property record with it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('properties', sa.Column(
        'recorded_owner_account_id', sa.Integer(),
        sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True))
    op.add_column('properties', sa.Column(
        'manager_account_id', sa.Integer(),
        sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True))
    op.add_column('properties', sa.Column(
        'tax_bill_account_id', sa.Integer(),
        sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True))

    op.create_index('idx_properties_recorded_owner_account_id', 'properties',
                     ['recorded_owner_account_id'])


def downgrade() -> None:
    op.drop_index('idx_properties_recorded_owner_account_id', table_name='properties')
    op.drop_column('properties', 'tax_bill_account_id')
    op.drop_column('properties', 'manager_account_id')
    op.drop_column('properties', 'recorded_owner_account_id')
