"""add_parcels_regrid

Revision ID: 432360b14f75
Revises: 81816f53fdda
Create Date: 2026-06-24 13:17:53.880619

New parcels_regrid table for the Regrid county-CSV reconciler — distinct
from the legacy Oakland-County-only `parcels` table (raw SQL, fixed
columns). No owner_id: like ENRICHMENT_CACHE, raw parcel facts are shared
reference data, not per-broker. See CLAUDE.md's PARCELS_REGRID section.

Also makes suggestions.entity_id_b nullable: the existing suggestions
table was built exclusively for account_duplicate (both sides are
accounts.id). The new regrid_owner_match producer only has one account
side (the candidate match) — the parcel side isn't an accounts.id and
goes in evidence JSON instead, so entity_id_b has nothing to hold there.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '432360b14f75'
down_revision: Union[str, None] = '81816f53fdda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'parcels_regrid',
        sa.Column('id',                sa.Integer(), nullable=False),
        sa.Column('parcel_id',         sa.Text(),    nullable=False),
        sa.Column('owner_raw',         sa.Text(),    nullable=True),
        sa.Column('owner_normalized',  sa.Text(),    nullable=True),
        sa.Column('address',           sa.Text(),    nullable=True),
        sa.Column('city',              sa.Text(),    nullable=True),
        sa.Column('state',             sa.Text(),    nullable=True),
        sa.Column('zip',               sa.Text(),    nullable=True),
        sa.Column('county',            sa.Text(),    nullable=True),
        sa.Column('geometry_wkt',      sa.Text(),    nullable=True),
        sa.Column('raw_data',          sa.JSON(),    nullable=True),
        sa.Column('ingested_at',       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('source_county',     sa.Text(),    nullable=False),
        sa.Column('reconciliation_status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('matched_account_id',  sa.Integer(), nullable=True),
        sa.Column('matched_property_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['matched_account_id'],  ['accounts.id'],   ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['matched_property_id'], ['properties.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('parcel_id', 'source_county', name='uq_parcels_regrid_parcel_county'),
    )
    op.create_index('ix_parcels_regrid_owner_normalized', 'parcels_regrid', ['owner_normalized'])
    op.create_index('ix_parcels_regrid_parcel_id', 'parcels_regrid', ['parcel_id'])
    op.create_index('ix_parcels_regrid_reconciliation_status', 'parcels_regrid', ['reconciliation_status'])

    op.alter_column('suggestions', 'entity_id_b', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('suggestions', 'entity_id_b', existing_type=sa.Integer(), nullable=False)
    op.drop_index('ix_parcels_regrid_reconciliation_status', table_name='parcels_regrid')
    op.drop_index('ix_parcels_regrid_parcel_id', table_name='parcels_regrid')
    op.drop_index('ix_parcels_regrid_owner_normalized', table_name='parcels_regrid')
    op.drop_table('parcels_regrid')
