"""add_national_locations

Revision ID: 1323d6d9faea
Revises: 432360b14f75
Create Date: 2026-06-25

national_locations: shared reference table (no owner_id) for Overture
Maps Places data — Michigan retail/restaurant/etc locations, quarterly
refresh via scripts/ingest_overture_michigan.py.

property_national_location_links: junction giving each broker's properties
their 'In your book' state against the shared location dataset.

See CLAUDE.md NATIONAL_LOCATIONS section for schema design notes.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '1323d6d9faea'
down_revision: Union[str, None] = '432360b14f75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'national_locations',
        sa.Column('id',               sa.Integer(),               nullable=False),
        sa.Column('overture_id',      sa.Text(),                  nullable=False),
        sa.Column('brand_primary',    sa.Text(),                  nullable=True),
        sa.Column('brand_normalized', sa.Text(),                  nullable=True),
        sa.Column('name_primary',     sa.Text(),                  nullable=True),
        sa.Column('category_primary', sa.Text(),                  nullable=True),
        sa.Column('category_top',     sa.Text(),                  nullable=True),
        sa.Column('address',          sa.Text(),                  nullable=True),
        sa.Column('city',             sa.Text(),                  nullable=True),
        sa.Column('state',            sa.Text(),                  nullable=True),
        sa.Column('zip',              sa.Text(),                  nullable=True),
        sa.Column('lat',              sa.Numeric(9, 6),           nullable=True),
        sa.Column('lng',              sa.Numeric(9, 6),           nullable=True),
        sa.Column('websites',         sa.JSON(),                  nullable=True),
        sa.Column('phones',           sa.JSON(),                  nullable=True),
        sa.Column('confidence',       sa.Numeric(4, 3),           nullable=True),
        sa.Column('raw_data',         sa.JSON(),                  nullable=True),
        sa.Column('release_version',  sa.Text(),                  nullable=True),
        sa.Column('ingested_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('overture_id', name='uq_national_locations_overture_id'),
    )
    op.create_index('ix_national_locations_id',              'national_locations', ['id'])
    op.create_index('ix_national_locations_overture_id',     'national_locations', ['overture_id'])
    op.create_index('ix_national_locations_brand_normalized','national_locations', ['brand_normalized'])
    op.create_index('ix_national_locations_category_top',    'national_locations', ['category_top'])
    op.create_index('ix_national_locations_state_city',      'national_locations', ['state', 'city'])
    op.create_index('ix_national_locations_lat_lng',         'national_locations', ['lat',   'lng'])

    op.create_table(
        'property_national_location_links',
        sa.Column('id',                   sa.Integer(),               nullable=False),
        sa.Column('property_id',          sa.Integer(),               nullable=False),
        sa.Column('national_location_id', sa.Integer(),               nullable=False),
        sa.Column('match_confidence',     sa.Numeric(4, 3),           nullable=True),
        sa.Column('created_at',           sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['property_id'],          ['properties.id'],         ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['national_location_id'], ['national_locations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('property_id', 'national_location_id', name='uq_pnll_property_location'),
    )
    op.create_index('ix_pnll_id',             'property_national_location_links', ['id'])
    op.create_index('ix_pnll_property_id',    'property_national_location_links', ['property_id'])
    op.create_index('ix_pnll_location_id',    'property_national_location_links', ['national_location_id'])


def downgrade() -> None:
    op.drop_table('property_national_location_links')
    op.drop_index('ix_national_locations_lat_lng',          table_name='national_locations')
    op.drop_index('ix_national_locations_state_city',       table_name='national_locations')
    op.drop_index('ix_national_locations_category_top',     table_name='national_locations')
    op.drop_index('ix_national_locations_brand_normalized', table_name='national_locations')
    op.drop_index('ix_national_locations_overture_id',      table_name='national_locations')
    op.drop_index('ix_national_locations_id',               table_name='national_locations')
    op.drop_table('national_locations')
