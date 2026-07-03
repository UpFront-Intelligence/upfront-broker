"""add_parcels_regrid_searchable_fields

Revision ID: 97ff9ec4ed1c
Revises: 04aa60723785
Create Date: 2026-07-03

Promotes ten fields from parcels_regrid.raw_data JSON into dedicated,
indexed columns, per the 2026-07-03 field-population recon (169-column
Regrid schema confirmed identical across all ingested counties; only
population RATES differ by county, not column names -- see CLAUDE.md's
PARCELS_REGRID section).

Purely additive: ADD COLUMN / CREATE INDEX on parcels_regrid only. No
other table is touched, no column is dropped or altered, no data is
migrated by this file (the re-ingest script populates these columns
separately, as a normal application-level UPSERT, not a migration data
migration).

centroid_lat/centroid_lng are plain DOUBLE PRECISION columns with a
composite btree index -- NOT PostGIS/GiST. This DB has no PostGIS
extension installed (deliberately deferred, see CLAUDE.md's PARCELS
section), and enabling one is a database-level operation, not a
purely-additive change to this one table. The composite btree here
mirrors the exact existing precedent for national_locations' own
lat/lng columns (ix_national_locations_lat_lng, migration 1323d6d9faea).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION


revision: str = '97ff9ec4ed1c'
down_revision: Union[str, None] = '04aa60723785'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('parcels_regrid', sa.Column('usecode',        sa.Text(),                nullable=True))
    op.add_column('parcels_regrid', sa.Column('usedesc',        sa.Text(),                nullable=True))
    op.add_column('parcels_regrid', sa.Column('assessed_value', sa.Numeric(14, 2),        nullable=True))
    op.add_column('parcels_regrid', sa.Column('sale_price',     sa.Numeric(14, 2),        nullable=True))
    op.add_column('parcels_regrid', sa.Column('sale_date',      sa.Date(),                nullable=True))
    op.add_column('parcels_regrid', sa.Column('lot_acres',      sa.Numeric(10, 5),        nullable=True))
    op.add_column('parcels_regrid', sa.Column('zoning',         sa.Text(),                nullable=True))
    op.add_column('parcels_regrid', sa.Column('land_use',       sa.Text(),                nullable=True))
    op.add_column('parcels_regrid', sa.Column('centroid_lat',   DOUBLE_PRECISION(),       nullable=True))
    op.add_column('parcels_regrid', sa.Column('centroid_lng',   DOUBLE_PRECISION(),       nullable=True))

    op.create_index('ix_parcels_regrid_usecode',        'parcels_regrid', ['usecode'])
    op.create_index('ix_parcels_regrid_assessed_value', 'parcels_regrid', ['assessed_value'])
    op.create_index('ix_parcels_regrid_sale_price',     'parcels_regrid', ['sale_price'])
    op.create_index('ix_parcels_regrid_lot_acres',      'parcels_regrid', ['lot_acres'])
    op.create_index('ix_parcels_regrid_centroid',       'parcels_regrid', ['centroid_lat', 'centroid_lng'])


def downgrade() -> None:
    op.drop_index('ix_parcels_regrid_centroid',       table_name='parcels_regrid')
    op.drop_index('ix_parcels_regrid_lot_acres',       table_name='parcels_regrid')
    op.drop_index('ix_parcels_regrid_sale_price',      table_name='parcels_regrid')
    op.drop_index('ix_parcels_regrid_assessed_value',  table_name='parcels_regrid')
    op.drop_index('ix_parcels_regrid_usecode',         table_name='parcels_regrid')

    op.drop_column('parcels_regrid', 'centroid_lng')
    op.drop_column('parcels_regrid', 'centroid_lat')
    op.drop_column('parcels_regrid', 'land_use')
    op.drop_column('parcels_regrid', 'zoning')
    op.drop_column('parcels_regrid', 'lot_acres')
    op.drop_column('parcels_regrid', 'sale_date')
    op.drop_column('parcels_regrid', 'sale_price')
    op.drop_column('parcels_regrid', 'assessed_value')
    op.drop_column('parcels_regrid', 'usedesc')
    op.drop_column('parcels_regrid', 'usecode')
