"""upgrade tenants module — top-level entity + property_tenants junction

Revision ID: b2c3d4e5f6a7
Revises: f6g7h8i9j0k1
Create Date: 2026-06-09

Drops the single-table tenants design from f6g7h8i9j0k1 and replaces it with:
  tenants          — top-level entity (the company / occupant)
  property_tenants — junction (the specific space / lease)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop old flat tenants table ───────────────────────────────────────────
    op.drop_index('idx_tenants_tenant_name', table_name='tenants')
    op.drop_index('idx_tenants_owner_id',    table_name='tenants')
    op.drop_index('idx_tenants_property_id', table_name='tenants')
    op.drop_table('tenants')

    # ── New tenants table — top-level entity ──────────────────────────────────
    op.create_table(
        'tenants',
        sa.Column('id',              sa.Integer(),                  nullable=False),
        sa.Column('owner_id',        sa.Integer(),                  nullable=False),
        sa.Column('name',            sa.String(),                   nullable=False),
        sa.Column('normalized_name', sa.String(),  server_default='', nullable=False),
        sa.Column('industry',        sa.String(),                   nullable=True),
        sa.Column('website',         sa.String(),                   nullable=True),
        sa.Column('hq_address',      sa.String(),                   nullable=True),
        sa.Column('hq_city',         sa.String(),                   nullable=True),
        sa.Column('hq_state',        sa.String(),                   nullable=True),
        sa.Column('hq_zip',          sa.String(),                   nullable=True),
        sa.Column('notes',           sa.Text(),                     nullable=True),
        sa.Column('created_at',      sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tenants_owner_id',        'tenants', ['owner_id'])
    op.create_index('idx_tenants_name',            'tenants', ['name'])
    op.create_index('idx_tenants_normalized_name', 'tenants', ['normalized_name'])

    # ── property_tenants — space / lease junction ─────────────────────────────
    op.create_table(
        'property_tenants',
        sa.Column('id',              sa.Integer(), nullable=False),
        sa.Column('owner_id',        sa.Integer(), nullable=False),
        sa.Column('property_id',     sa.Integer(), nullable=False),
        sa.Column('tenant_id',       sa.Integer(), nullable=False),
        sa.Column('sf',              sa.Integer(), nullable=True),
        sa.Column('pct_of_building', sa.Float(),   nullable=True),
        sa.Column('rent_per_sf',     sa.Float(),   nullable=True),
        sa.Column('lease_type',      sa.String(),  nullable=True),
        sa.Column('lease_start',     sa.Date(),    nullable=True),
        sa.Column('lease_expiry',    sa.Date(),    nullable=True),
        sa.Column('is_available',    sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('notes',           sa.Text(),    nullable=True),
        sa.ForeignKeyConstraint(['owner_id'],    ['users.id']),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenants.id'],    ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pt_property_id', 'property_tenants', ['property_id'])
    op.create_index('idx_pt_tenant_id',   'property_tenants', ['tenant_id'])
    op.create_index('idx_pt_owner_id',    'property_tenants', ['owner_id'])


def downgrade() -> None:
    op.drop_index('idx_pt_owner_id',    table_name='property_tenants')
    op.drop_index('idx_pt_tenant_id',   table_name='property_tenants')
    op.drop_index('idx_pt_property_id', table_name='property_tenants')
    op.drop_table('property_tenants')

    op.drop_index('idx_tenants_normalized_name', table_name='tenants')
    op.drop_index('idx_tenants_name',            table_name='tenants')
    op.drop_index('idx_tenants_owner_id',        table_name='tenants')
    op.drop_table('tenants')
