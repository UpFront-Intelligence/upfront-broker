"""add tenants table

Revision ID: f6g7h8i9j0k1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('id',             sa.Integer(),  nullable=False),
        sa.Column('property_id',    sa.Integer(),  nullable=False),
        sa.Column('tenant_name',    sa.String(),   nullable=False),
        sa.Column('sf',             sa.Integer(),  nullable=True),
        sa.Column('pct_of_building',sa.Float(),    nullable=True),
        sa.Column('lease_expiry',   sa.Date(),     nullable=True),
        sa.Column('is_available',   sa.Boolean(),  nullable=True, server_default='false'),
        sa.Column('notes',          sa.Text(),     nullable=True),
        sa.Column('owner_id',       sa.Integer(),  nullable=False),
        sa.ForeignKeyConstraint(['owner_id'],    ['users.id']),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tenants_property_id', 'tenants', ['property_id'])
    op.create_index('idx_tenants_owner_id',    'tenants', ['owner_id'])
    op.create_index('idx_tenants_tenant_name', 'tenants', ['tenant_name'])


def downgrade() -> None:
    op.drop_index('idx_tenants_tenant_name', table_name='tenants')
    op.drop_index('idx_tenants_owner_id',    table_name='tenants')
    op.drop_index('idx_tenants_property_id', table_name='tenants')
    op.drop_table('tenants')
