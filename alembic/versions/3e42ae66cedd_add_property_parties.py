"""add property_parties junction table

Revision ID: 3e42ae66cedd
Revises: df65bcec62ab
Create Date: 2026-06-18

property_parties — every party linked to a property gets an explicit row
with a role (leasing_broker / owner / sale_broker / tenant_rep / manager /
tax_bill), instead of just an account FK on properties. A party is either
an Account or a Contact (at least one set; either may be set on its own).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3e42ae66cedd'
down_revision: Union[str, None] = 'df65bcec62ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'property_parties',
        sa.Column('id',          sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('account_id',  sa.Integer(), nullable=True),
        sa.Column('contact_id',  sa.Integer(), nullable=True),
        sa.Column('role',        sa.Text(),    nullable=False),
        sa.Column('source',      sa.Text(),    nullable=False, server_default='import'),
        sa.Column('note',        sa.Text(),    nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'],  ['accounts.id'],  ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'],  ['contacts.id'],  ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            'num_nonnulls(account_id, contact_id) >= 1',
            name='chk_pp_at_least_one_entity',
        ),
    )
    op.create_index(
        'uix_pp_property_account_role',
        'property_parties',
        ['property_id', 'account_id', 'role'],
        unique=True,
        postgresql_where=sa.text('account_id IS NOT NULL'),
    )
    op.create_index(
        'uix_pp_property_contact_role',
        'property_parties',
        ['property_id', 'contact_id', 'role'],
        unique=True,
        postgresql_where=sa.text('contact_id IS NOT NULL'),
    )
    op.create_index('idx_pp_property_id', 'property_parties', ['property_id'])


def downgrade() -> None:
    op.drop_index('idx_pp_property_id',             table_name='property_parties')
    op.drop_index('uix_pp_property_contact_role',   table_name='property_parties')
    op.drop_index('uix_pp_property_account_role',   table_name='property_parties')
    op.drop_table('property_parties')
